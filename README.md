# Video Background Removal Tool

A web-based tool for removing video backgrounds using Segment Anything Model (SAM) and adding green screen effects.

## Setup

1. Clone the repository
```bash
git clone <your-repo-url>
cd <repo-directory>
```

2. Install dependencies
```bash
pip install -r requirements.txt
```

3. Configure environment variables
   - Copy `.env.example` to `.env`
   - Fill in the following variables in `.env`:
     - `REPLICATE_API_TOKEN`: Your Replicate API token
     - `GCP_CREDENTIALS_PATH`: Path to your Google Cloud credentials JSON file
     - `GCP_BUCKET_NAME`: Your Google Cloud Storage bucket name

4. Set up Google Cloud credentials
   - Place your Google Cloud credentials JSON file in the project root
   - Make sure the path matches `GCP_CREDENTIALS_PATH` in your `.env`

## Usage

1. Run the application:
```bash
python run.py
```

2. Open your browser and navigate to `http://localhost:3002`

3. Use the web interface to:
   - Input video URLs
   - Mark points for background removal
   - Process videos
   - Download results with green screen effects

## Security Notes

- Never commit your `.env` file or Google Cloud credentials to version control
- Keep your API tokens and credentials secure
- The `.gitignore` file is configured to exclude sensitive files 