import cv2
import numpy as np
import urllib.request
import json
import tkinter as tk
from tkinter import ttk, scrolledtext
from PIL import Image, ImageTk
import threading
from io import StringIO
from flask import Flask, render_template_string, jsonify, request, send_file
import webbrowser
import socket
import sys
import base64
import replicate
import asyncio
from dotenv import load_dotenv
import os
import tempfile
import requests
from google.cloud import storage
import uuid

# Load environment variables from .env file
load_dotenv()

# Configure Replicate API token
os.environ["REPLICATE_API_TOKEN"] = os.getenv("REPLICATE_API_TOKEN")

# Configure GCP credentials
GCP_CREDENTIALS_PATH = os.getenv("GCP_CREDENTIALS_PATH", "key.json")
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = GCP_CREDENTIALS_PATH

# GCP bucket name
BUCKET_NAME = os.getenv("GCP_BUCKET_NAME")

def upload_to_gcp(local_file_path, destination_blob_name=None):
    """Uploads a file to GCP bucket."""
    try:
        # If no destination name provided, use the local filename with a UUID
        if destination_blob_name is None:
            file_extension = os.path.splitext(local_file_path)[1]
            destination_blob_name = f"greenscreen_{uuid.uuid4()}{file_extension}"

        print(f"Uploading to GCP bucket: {destination_blob_name}")

        # Initialize GCP storage client
        storage_client = storage.Client()
        bucket = storage_client.bucket(BUCKET_NAME)
        blob = bucket.blob(destination_blob_name)
        generation_match_precondition = 0
        # Upload the file
        blob.upload_from_filename(local_file_path, if_generation_match=generation_match_precondition)

        # Get the public URL
        public_url = f"https://storage.googleapis.com/{BUCKET_NAME}/{destination_blob_name}"
        return public_url

    except Exception as e:
        print(f"Error uploading to GCP: {str(e)}")
        return None

app = Flask(__name__)

# HTML template for the web interface
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Video Annotator</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            margin: 0;
            padding: 20px;
            display: flex;
        }
        .left-panel {
            flex: 2;
            padding-right: 20px;
        }
        .right-panel {
            flex: 1;
            padding-left: 20px;
            border-left: 1px solid #ccc;
        }
        .url-input {
            width: 100%;
            margin-bottom: 10px;
        }
        .url-list {
            width: 100%;
            height: 100px;
            margin-bottom: 10px;
        }
        .canvas-container {
            border: 1px solid #ccc;
            margin-bottom: 10px;
            position: relative;
            width: fit-content;
        }
        #imageCanvas {
            height: 300px;  /* Fixed display height */
            width: auto;    /* Width will adjust to maintain aspect ratio */
        }
        .button-group {
            margin-bottom: 10px;
        }
        .coordinates-display {
            border: 1px solid #ccc;
            padding: 10px;
            margin: 10px 0;
            background: #f5f5f5;
            max-height: 200px;
            overflow-y: auto;
        }
        .coordinates-title {
            font-weight: bold;
            margin-bottom: 5px;
        }
        .results {
            width: 100%;
            height: 500px;
        }
        .status-bar {
            position: fixed;
            bottom: 0;
            left: 0;
            right: 0;
            padding: 10px;
            background: #f0f0f0;
            border-top: 1px solid #ccc;
        }
        .download-buttons {
            margin-top: 20px;
            display: flex;
            flex-direction: column;
            gap: 10px;
        }
        .download-button {
            padding: 10px;
            background: #4CAF50;
            color: white;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            text-align: left;
            font-size: 14px;
        }
        .download-button:hover {
            background: #45a049;
        }
    </style>
</head>
<body>
    <div class="left-panel">
        <div>
            <input type="text" id="urlInput" class="url-input" placeholder="Enter video URL">
            <button onclick="addUrl()">Add URL</button>
        </div>
        <textarea id="urlList" class="url-list" readonly></textarea>
        <div class="canvas-container">
            <canvas id="imageCanvas"></canvas>
        </div>
        <div class="button-group">
            <button onclick="startProcessing()">Start Processing</button>
            <button onclick="doneWithCurrent()">Done with Current Video</button>
            <button onclick="clearPoints()">Clear Points</button>
        </div>
        <div class="coordinates-display">
            <div class="coordinates-title">Selected Points (Original Image Coordinates):</div>
            <div id="coordsList"></div>
        </div>
    </div>
    <div class="right-panel">
        <textarea id="results" class="results" readonly></textarea>
        <div id="resultLinks"></div>
        <div id="downloadButtons" class="download-buttons"></div>
    </div>
    <div class="status-bar" id="status">Ready</div>

    <script>
        let videoUrls = [];
        let coordinates = [];
        let currentVideoIdx = -1;
        
        function setStatus(message) {
            document.getElementById('status').textContent = message;
        }
        
        function addUrl() {
            const urlInput = document.getElementById('urlInput');
            const url = urlInput.value.trim();
            if (url) {
                videoUrls.push(url);
                document.getElementById('urlList').value += url + '\\n';
                urlInput.value = '';
            }
        }
        
        function clearPoints() {
            coordinates = [];
            drawPoints();
            setStatus('Cleared all points');
        }
        
        async function startProcessing() {
            if (videoUrls.length === 0) {
                setStatus('Please add some video URLs first');
                return;
            }
            
            currentVideoIdx = -1;
            document.getElementById('results').value = '';
            await processNextVideo();
        }
        
        async function processNextVideo() {
            currentVideoIdx++;
            if (currentVideoIdx >= videoUrls.length) {
                setStatus('Finished processing all videos');
                return;
            }
            
            setStatus(`Processing video ${currentVideoIdx + 1}/${videoUrls.length}`);
            
            try {
                const response = await fetch('/process_video', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        url: videoUrls[currentVideoIdx]
                    })
                });
                
                const data = await response.json();
                if (data.error) {
                    setStatus(`Error: ${data.error}`);
                    return;
                }
                
                // Display the frame with scaling
                const img = new Image();
                img.onload = function() {
                    const canvas = document.getElementById('imageCanvas');
                    
                    // Calculate scaling factor to maintain aspect ratio with 300px height
                    const scale = 300 / img.naturalHeight;
                    
                    // Set scaled dimensions
                    canvas.style.height = '300px';
                    canvas.style.width = (img.naturalWidth * scale) + 'px';
                    
                    // Set actual canvas dimensions for proper rendering
                    canvas.width = img.naturalWidth;
                    canvas.height = img.naturalHeight;
                    
                    const ctx = canvas.getContext('2d');
                    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
                    
                    // Store original dimensions and scale for coordinate conversion
                    canvas.dataset.originalWidth = img.naturalWidth;
                    canvas.dataset.originalHeight = img.naturalHeight;
                    canvas.dataset.scale = scale;
                    
                    // Display image dimensions
                    setStatus(`Image loaded - Original dimensions: ${img.naturalWidth}x${img.naturalHeight}px, Scale: ${scale.toFixed(3)}`);
                    updateCoordinatesDisplay();
                };
                img.src = data.frame;
                
                coordinates = [];
                drawPoints();
                
            } catch (error) {
                setStatus(`Error: ${error.message}`);
            }
        }
        
        function drawPoints() {
            const canvas = document.getElementById('imageCanvas');
            const ctx = canvas.getContext('2d');
            const scale = parseFloat(canvas.dataset.scale);
            
            // Clear and redraw image
            const img = new Image();
            img.onload = function() {
                ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
                
                // Draw points
                coordinates.forEach((point, index) => {
                    const displayX = point[0] * scale;
                    const displayY = point[1] * scale;
                    
                    ctx.beginPath();
                    ctx.arc(point[0], point[1], 5, 0, 2 * Math.PI);
                    ctx.fillStyle = 'red';
                    ctx.fill();
                    
                    ctx.fillStyle = 'white';
                    ctx.strokeStyle = 'red';
                    ctx.lineWidth = 2;
                    ctx.font = '16px Arial';
                    const text = (index + 1).toString();
                    const textWidth = ctx.measureText(text).width;
                    
                    // Draw text background
                    ctx.fillStyle = 'red';
                    ctx.fillRect(point[0] + 10, point[1] - 8, textWidth + 4, 16);
                    
                    // Draw text
                    ctx.fillStyle = 'white';
                    ctx.fillText(text, point[0] + 12, point[1] + 4);
                });
            };
            img.src = document.getElementById('imageCanvas').toDataURL();
        }
        
        function updateCoordinatesDisplay() {
            const coordsList = document.getElementById('coordsList');
            coordsList.innerHTML = coordinates.map((coord, index) => {
                return `Point ${index + 1}: (${coord[0]}, ${coord[1]})`;
            }).join('<br>');
        }
        
        document.getElementById('imageCanvas').addEventListener('click', function(event) {
            const canvas = event.target;
            const rect = canvas.getBoundingClientRect();
            
            // Get click position relative to the displayed (scaled) image
            const displayX = event.clientX - rect.left;
            const displayY = event.clientY - rect.top;
            
            // Convert to original image coordinates
            const scale = parseFloat(canvas.dataset.scale);
            const x = Math.round(displayX / scale);
            const y = Math.round(displayY / scale);
            
            coordinates.push([x, y]);
            drawPoints();
            updateCoordinatesDisplay();
            setStatus(`Added point at original coordinates: (${x}, ${y})`);
        });
        
        async function doneWithCurrent() {
            if (currentVideoIdx < 0) return;
            
            try {
                setStatus('Processing annotations and running AI model...');
                const response = await fetch('/save_annotations', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        url: videoUrls[currentVideoIdx],
                        coordinates: coordinates
                    })
                });
                
                const data = await response.json();
                if (data.error) {
                    setStatus(`Error: ${data.error}`);
                    return;
                }
                
                // Display the result URL in the results textarea
                if (data.output) {
                    document.getElementById('results').value += `\nProcessed Video ${currentVideoIdx + 1}:\n${data.output}\n`;
                    
                    // Add buttons container
                    const buttonContainer = document.getElementById('downloadButtons');
                    
                    // Button to view original result
                    const viewButton = document.createElement('button');
                    viewButton.className = 'download-button';
                    const videoName = videoUrls[currentVideoIdx].split('/').pop();
                    viewButton.textContent = `${videoName}: View Original`;
                    viewButton.onclick = function() {
                        window.open(data.output, '_blank');
                        setStatus(`Opening original result for ${videoName} in new tab`);
                    };
                    
                    // Button to download green screen version
                    const downloadButton = document.createElement('button');
                    downloadButton.className = 'download-button';
                    downloadButton.textContent = `${videoName}: Download Green Screen Version`;
                    downloadButton.onclick = function() {
                        setStatus(`Processing and downloading green screen version for ${videoName}...`);
                        window.location.href = `/process_and_download/${data.video_id}`;
                    };
                    
                    buttonContainer.appendChild(viewButton);
                    buttonContainer.appendChild(downloadButton);
                }
                
                setStatus('Processing complete. Moving to next video...');
                await processNextVideo();
                
            } catch (error) {
                setStatus(`Error: ${error.message}`);
            }
        }
    </script>
</body>
</html>
'''

# Store video frames and annotations
video_frames = {}
video_annotations = {}

@app.route('/')
def home():
    return render_template_string(HTML_TEMPLATE)

@app.route('/process_video', methods=['POST'])
def process_video():
    try:
        data = request.get_json()
        url = data['url']
        
        # Download and process video
        video_path = download_video(url)
        cap = cv2.VideoCapture(video_path)
        ret, frame = cap.read()
        cap.release()
        
        if not ret:
            return jsonify({'error': 'Failed to read video frame'})
        
        # Convert frame to base64
        _, buffer = cv2.imencode('.jpg', frame)
        frame_b64 = base64.b64encode(buffer).decode('utf-8')
        
        # Store frame for later use
        video_frames[url] = frame
        
        return jsonify({
            'frame': f'data:image/jpeg;base64,{frame_b64}'
        })
        
    except Exception as e:
        return jsonify({'error': str(e)})

def process_video_with_green_screen(video_url):
    # Create temp files for processing
    temp_input = tempfile.NamedTemporaryFile(suffix='.mp4', delete=False).name
    temp_output = tempfile.NamedTemporaryFile(suffix='.mp4', delete=False).name
    
    try:
        # Download the video
        response = requests.get(video_url)
        with open(temp_input, 'wb') as f:
            f.write(response.content)
        
        # Open the video
        cap = cv2.VideoCapture(temp_input)
        
        # Get video properties
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = int(cap.get(cv2.CAP_PROP_FPS))
        
        # Create VideoWriter object
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(temp_output, fourcc, fps, (width, height))
        
        # Green screen color (RGB)
        green_color = [0, 255, 0]  # Green in BGR
        
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break
            
            # Convert frame to grayscale for mask detection
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            
            # Create mask where black pixels (background) are found
            # Threshold value of 10 to account for compression artifacts
            mask = gray < 10
            
            # Create output frame
            output_frame = frame.copy()
            
            # Replace black pixels with green
            output_frame[mask] = green_color
            
            # Write the frame
            out.write(output_frame)
        
        # Release everything
        cap.release()
        out.release()
        
        return temp_output
        
    except Exception as e:
        print(f"Error processing video: {str(e)}")
        if os.path.exists(temp_input):
            os.unlink(temp_input)
        if os.path.exists(temp_output):
            os.unlink(temp_output)
        return None

@app.route('/process_and_download/<video_id>')
def process_and_download(video_id):
    try:
        # Get the original video URL from stored data
        video_url = f"https://replicate.delivery/xezq/{video_id}/output_video.mp4"
        
        # Process the video
        processed_video_path = process_video_with_green_screen(video_url)
        
        if processed_video_path:
            return send_file(
                processed_video_path,
                as_attachment=True,
                download_name='processed_video_greenscreen.mp4',
                mimetype='video/mp4'
            )
        else:
            return jsonify({'error': 'Failed to process video'})
            
    except Exception as e:
        return jsonify({'error': str(e)})

def process_video_with_mask(original_url, mask_url):
    # Create output directory if it doesn't exist
    output_dir = "output"
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    # Create temp files for processing
    temp_original = tempfile.NamedTemporaryFile(suffix='.mp4', delete=False).name
    temp_mask = tempfile.NamedTemporaryFile(suffix='.mp4', delete=False).name
    
    # Create a unique filename for local storage
    local_filename = f'greenscreen_{uuid.uuid4()}.mp4'
    output_path = os.path.join(output_dir, local_filename)

    try:
        # Download both videos
        print("Downloading original video...")
        response = requests.get(original_url)
        with open(temp_original, 'wb') as f:
            f.write(response.content)

        print("Downloading mask video...")
        response = requests.get(mask_url)
        with open(temp_mask, 'wb') as f:
            f.write(response.content)

        # Open both videos
        cap_original = cv2.VideoCapture(temp_original)
        cap_mask = cv2.VideoCapture(temp_mask)

        # Get video properties from original video
        width = int(cap_original.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap_original.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = int(cap_original.get(cv2.CAP_PROP_FPS))

        # Create VideoWriter object
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(output_path, fourcc, fps, (width, height))

        # Green screen color (BGR)
        green_color = [0, 255, 0]

        while True:
            ret_original, frame_original = cap_original.read()
            ret_mask, frame_mask = cap_mask.read()

            if not ret_original or not ret_mask:
                break

            # Convert mask frame to grayscale
            mask_gray = cv2.cvtColor(frame_mask, cv2.COLOR_BGR2GRAY)
            
            # Create binary mask where black pixels are found
            # Threshold value of 10 to account for compression artifacts
            mask = mask_gray < 10

            # Create output frame
            output_frame = frame_original.copy()
            
            # Replace masked pixels with green
            output_frame[mask] = green_color

            # Write the frame
            out.write(output_frame)

        # Release everything
        cap_original.release()
        cap_mask.release()
        out.release()

        # Upload to GCP bucket
        print("Uploading to GCP bucket...")
        gcp_url = upload_to_gcp(output_path, local_filename)
        
        if gcp_url:
            print(f"Video uploaded successfully: {gcp_url}")
            return {
                'local_path': output_path,
                'gcp_url': gcp_url
            }
        else:
            print("Failed to upload to GCP bucket")
            return {
                'local_path': output_path,
                'gcp_url': None
            }

    except Exception as e:
        print(f"Error processing video with mask: {str(e)}")
        if os.path.exists(temp_original):
            os.unlink(temp_original)
        if os.path.exists(temp_mask):
            os.unlink(temp_mask)
        return None

@app.route('/save_annotations', methods=['POST'])
def save_annotations():
    try:
        data = request.get_json()
        url = data['url']
        coordinates = data['coordinates']
        
        # Create JSON output
        coord_str = ','.join([f"[{x},{y}]" for x, y in coordinates])
        json_output = {
            "mask_type": "binary",
            "video_fps": 25,
            "input_video": url,
            "click_frames": ','.join(['0'] * len(coordinates)),
            "click_labels": ','.join(['1'] * len(coordinates)),
            "output_video": True,
            "output_format": "webp",
            "output_quality": 100,
            "annotation_type": "mask",
            "click_object_ids": "mask_1",
            "click_coordinates": coord_str,
            "output_frame_interval": 1
        }
        
        # Store annotations
        video_annotations[url] = json_output
        
        try:
            print("\nMaking API call to Replicate...")
            output = replicate.run(
                "meta/sam-2-video:33432afdfc06a10da6b4018932893d39b0159f838b6d11dd1236dff85cc5ec1d",
                input=json_output
            )
            print(output)
            
            result_url = None
            for item in output:
                result_url = item
            
            if result_url:
                # Process the videos to create green screen version
                print("Processing videos to create green screen version...")
                result = process_video_with_mask(url, result_url)
                
                if result:
                    return jsonify({
                        'video_id': str(data['url']),
                        'greenscreen_url': result['gcp_url']
                    })
                else:
                    return jsonify({
                        'error': 'Failed to create green screen version'
                    })
            else:
                return jsonify({
                    'error': 'No output URL found in API response'
                })
            
        except Exception as e:
            print(f"\nAPI Error: {str(e)}")
            return jsonify({
                'error': str(e)
            })
        
    except Exception as e:
        return jsonify({'error': str(e)})

def is_port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('localhost', port)) == 0

def download_video(url, save_path='temp_video.mp4'):
    """Download video from URL"""
    urllib.request.urlretrieve(url, save_path)
    return save_path

def main():
    # Check if port 3002 is available
    if is_port_in_use(3002):
        print("Error: Port 3002 is already in use")
        sys.exit(1)

    # Start Flask server
    print("Starting server at http://localhost:3002")
    webbrowser.open('http://localhost:3002')
    app.run(port=3002)

if __name__ == "__main__":
    main()
    # process_video_with_mask("https://storage.googleapis.com/2vid-temp-video-bckt/video_outf34e0aae-8420-4242-9d12-ba752b8c3225.mp4","https://replicate.delivery/xezq/qf0H6lY0Wh1eEEioBYxqlxxc7KDcfiuroEIaRmtQCwfPnMgQB/output_video.mp4")
