import json
import requests
import time
import re
from PIL import Image
from io import BytesIO
from flask import Flask, request, jsonify, render_template, redirect, url_for
import os

# Your bot token obtained from BotFather
BOT_TOKEN = '7080556956:AAF19uO0sBcOfLCgEt-f7dBV2swBtVkHMbU'
CHAT_ID = '5533681942'

app = Flask(__name__)

# Function to escape special characters for MarkdownV2
def escape_markdown_v2(text):
    escape_chars = r'\_*[]()~`>#+-=|{{}}.!'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)

# Function to download image from a URL
def download_image(url):
    headers = {{
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }}
    response = requests.get(url, headers=headers)
    if response.status_code == 200 and 'image' in response.headers['Content-Type']:
        img = Image.open(BytesIO(response.content))
        # Convert image mode if necessary
        if img.mode != 'RGB':
            img = img.convert('RGB')
        return img
    else:
        print(f"Error: Unable to download image. URL: {{url}}, Status Code: {{response.status_code}}, Content-Type: {{response.headers.get('Content-Type', '')}}")
        return None

@app.route('/', methods=['GET', 'POST'])
def upload_file():
    if request.method == 'POST':
        # Check if the post request has the file part
        if 'file' not in request.files:
            return "No file part", 400
        file = request.files['file']
        # If the user does not select a file, the browser submits an empty part without filename
        if file.filename == '':
            return "No selected file", 400
        if file and file.filename.endswith('.json'):
            file_path = os.path.join('uploads', file.filename)
            file.save(file_path)

            # Process the JSON file
            with open(file_path, "r", encoding="utf-8") as f:
                questions = json.load(f)
                process_quiz(questions)
            return "File uploaded and processed successfully"

    return render_template('index.html')

def process_quiz(questions):
    # Define the URL for sending a poll
    poll_url = f'https://api.telegram.org/bot{{BOT_TOKEN}}/sendPoll'
    # Define the URL for sending a message
    message_url = f'https://api.telegram.org/bot{{BOT_TOKEN}}/sendMessage'
    # Define the URL for sending a photo
    photo_url = f'https://api.telegram.org/bot{{BOT_TOKEN}}/sendPhoto'

    # Loop through each question and send it as a poll
    for question in questions:
        payload = {{
            'chat_id': CHAT_ID,
            'question': question['question'],
            'options': json.dumps(question['options']),
            'type': 'quiz',
            'correct_option_id': question['correct_option_id'],
        }}
        response = requests.post(poll_url, data=payload)

        # Check for success
        if response.status_code == 200:
            print(f"Successfully sent question: {{question['question']}}")

            # Escape the explanation text
            escaped_explanation = escape_markdown_v2(question['explanation'])

            # Send the explanation as a spoiler message
            explanation_payload = {{
                'chat_id': CHAT_ID,
                'text': f"||{{escaped_explanation}}||",  # Spoiler formatting
                'parse_mode': 'MarkdownV2'
            }}
            explanation_response = requests.post(message_url, data=explanation_payload)

            if explanation_response.status_code == 200:
                print(f"Successfully sent explanation for: {{question['question']}}")
            else:
                print(f"Failed to send explanation for: {{question['question']}}. Response: {{explanation_response.text}}")

            # Check if there's an image link
            image_link = question.get('image_link', None)
            if image_link:
                try:
                    img = download_image(image_link)
                    if img:
                        img_bytes = BytesIO()
                        img.save(img_bytes, format='JPEG')
                        img_bytes.seek(0)

                        photo_payload = {{
                            'chat_id': CHAT_ID,
                        }}
                        files = {{
                            'photo': img_bytes
                        }}
                        photo_response = requests.post(photo_url, data=photo_payload, files=files)

                        if photo_response.status_code == 200:
                            print(f"Successfully sent image for: {{question['question']}}")
                        else:
                            print(f"Failed to send image for: {{question['question']}}. Response: {{photo_response.text}}")
                    else:
                        print(f"Image download failed for question: {{question['question']}}")
                except Exception as e:
                    print(f"Error downloading or sending image for: {{question['question']}}. Error: {{e}}")
        else:
            print(f"Failed to send question: {{question['question']}}. Response: {{response.text}}")

        # To avoid hitting the rate limit, sleep for a bit
        time.sleep(1)  # Adjust the sleep time as needed

    print("All questions have been sent.")

if __name__ == "__main__":
    os.makedirs('uploads', exist_ok=True)
    app.run(debug=True, host='0.0.0.0')
