from flask import Flask, render_template, request, jsonify, send_file
from PIL import Image
from datetime import datetime
from imagekitio import ImageKit
import qrcode
import fitz  # PyMuPDF
import os
import io
import base64
import json

app = Flask(__name__)

# ImageKit Configuration - Set these in Render environment variables
IMAGEKIT_PRIVATE_KEY = os.environ.get('IMAGEKIT_PRIVATE_KEY', 'your_private_key')
IMAGEKIT_PUBLIC_KEY = os.environ.get('IMAGEKIT_PUBLIC_KEY', 'your_public_key')
IMAGEKIT_URL_ENDPOINT = os.environ.get('IMAGEKIT_URL_ENDPOINT', 'https://ik.imagekit.io/your_id')

# Initialize ImageKit
imagekit = ImageKit(
    private_key=IMAGEKIT_PRIVATE_KEY,
    public_key=IMAGEKIT_PUBLIC_KEY,
    url_endpoint=IMAGEKIT_URL_ENDPOINT
)

# Certificate coordinates (same as generate_certificates.py)
COORDS = {
    'name': {'y': 330, 'font_size': 16, 'centered': True},
    'course': {'x': 375, 'y': 263, 'font_size': 16},
    'duration': {'x': 230, 'y': 210, 'font_size': 16},
    'aadhaar': {'x': 187, 'y': 170, 'font_size': 16},
    'grade': {'x': 680, 'y': 167, 'font_size': 16},
    'doi': {'x': 470, 'y': 167, 'font_size': 16},
    'qr': {'x': 87, 'y': 87, 'width': 60, 'height': 60},
    'photo': {'x': 680, 'y': 450, 'width': 80, 'height': 100}
}

# Counter file for SR numbers
COUNTER_FILE = "certificate_counter.json"

def get_next_sr_no():
    if os.path.exists(COUNTER_FILE):
        with open(COUNTER_FILE, 'r') as f:
            data = json.load(f)
            return data.get('next_sr', 1)
    return 1

def save_sr_no(sr_no):
    with open(COUNTER_FILE, 'w') as f:
        json.dump({'next_sr': sr_no + 1}, f)

def create_verification_html(cert_id, name, course, aadhaar):
    return f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Certificate Verification - {cert_id}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            padding: 20px;
        }}
        .card {{
            background: white;
            border-radius: 20px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            max-width: 500px;
            width: 100%;
            padding: 40px;
        }}
        .header {{ text-align: center; margin-bottom: 30px; }}
        .header h1 {{ color: #667eea; font-size: 28px; margin-bottom: 10px; }}
        .header p {{ color: #666; font-size: 14px; }}
        .info-row {{
            margin: 20px 0;
            padding: 15px;
            background: #f8f9fa;
            border-radius: 10px;
            border-left: 4px solid #667eea;
        }}
        .info-label {{ color: #666; font-size: 12px; text-transform: uppercase; margin-bottom: 5px; }}
        .info-value {{ color: #333; font-size: 18px; font-weight: 600; }}
        .verified-badge {{
            background: #10b981;
            color: white;
            padding: 10px 20px;
            border-radius: 50px;
            text-align: center;
            margin-top: 30px;
            font-weight: 600;
        }}
    </style>
</head>
<body>
    <div class="card">
        <div class="header">
            <h1>✅ Verified Certificate</h1>
            <p>Certificate ID: {cert_id}</p>
        </div>
        <div class="info-row">
            <div class="info-label">Student Name</div>
            <div class="info-value">{name}</div>
        </div>
        <div class="info-row">
            <div class="info-label">Course</div>
            <div class="info-value">{course}</div>
        </div>
        <div class="info-row">
            <div class="info-label">Aadhaar Number</div>
            <div class="info-value">{aadhaar}</div>
        </div>
        <div class="verified-badge">✓ Verified & Authentic</div>
    </div>
</body>
</html>'''

def generate_qr_code(url):
    qr = qrcode.QRCode(version=1, box_size=10, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white")
    
    # Convert to bytes
    img_buffer = io.BytesIO()
    qr_img.save(img_buffer, format='PNG')
    img_buffer.seek(0)
    return img_buffer

def process_photo(photo_data):
    """Process uploaded photo - rotate if landscape"""
    img = Image.open(io.BytesIO(photo_data))
    
    if img.mode in ('RGBA', 'P'):
        img = img.convert('RGB')
    
    # Rotate if landscape
    if img.width > img.height:
        img = img.rotate(-90, expand=True)
    
    # Save to buffer
    buffer = io.BytesIO()
    img.save(buffer, format='JPEG', quality=95)
    buffer.seek(0)
    return buffer

def upload_to_imagekit(file_buffer, filename, cert_id):
    """Upload file to ImageKit in Generated_Certificates/CERT_ID/ folder"""
    try:
        # Convert to base64
        file_buffer.seek(0)
        file_base64 = base64.b64encode(file_buffer.read()).decode('utf-8')
        
        # Folder structure: Generated_Certificates/CERT0001/
        folder_path = f"/Generated_Certificates/{cert_id}"
        
        result = imagekit.upload_file(
            file=file_base64,
            file_name=filename,
            options={
                "folder": folder_path,
                "is_private_file": False
            }
        )
        
        return result.response_metadata.raw if hasattr(result, 'response_metadata') else result
    except Exception as e:
        print(f"ImageKit upload error: {e}")
        import traceback
        traceback.print_exc()
        return None

# Store certificate data in JSON file (simple database)
DATA_FILE = "certificates_data.json"

def load_certificates_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_certificate_data(cert_id, data):
    all_data = load_certificates_data()
    all_data[cert_id] = data
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(all_data, f, ensure_ascii=False, indent=2)

@app.route('/')
def index():
    sr_no = get_next_sr_no()
    return render_template('form.html', sr_no=sr_no, cert_id=f"CERT{sr_no:04d}")

@app.route('/generate', methods=['POST'])
def generate_certificate():
    try:
        # Get form data
        name = request.form.get('name', '').strip()
        course = request.form.get('course', '').strip()
        duration = request.form.get('duration', '').strip()
        aadhaar = request.form.get('aadhaar', '').strip()
        grade = request.form.get('grade', '').strip()
        doi = request.form.get('doi', '').strip()
        
        # Validate required fields
        if not all([name, course, aadhaar, doi]):
            return jsonify({'error': 'Please fill all required fields'}), 400
        
        # Get SR number
        sr_no = get_next_sr_no()
        cert_id = f"CERT{sr_no:04d}"
        
        # Process photo if uploaded
        photo_buffer = None
        if 'photo' in request.files:
            photo_file = request.files['photo']
            if photo_file.filename:
                photo_buffer = process_photo(photo_file.read())
        
        # Get the app's base URL for verification
        base_url = request.host_url.rstrip('/')
        verify_url = f"{base_url}/verify/{cert_id}"
        
        # Generate QR code pointing to our verify endpoint
        qr_buffer = generate_qr_code(verify_url)
        
        # Create certificate PDF
        template_path = "Usdc Certificate.pdf"
        if not os.path.exists(template_path):
            return jsonify({'error': 'Certificate template not found'}), 500
        
        doc = fitz.open(template_path)
        page = doc[0]
        page_height = page.rect.height
        page_width = page.rect.width
        
        # Add text fields
        # Name (centered)
        name_width = fitz.get_text_length(name, fontname="helv", fontsize=16)
        name_x = (page_width - name_width) / 2
        page.insert_text((name_x, page_height - 330), name, fontsize=16)
        
        # Course
        page.insert_text((375, page_height - 263), course, fontsize=16)
        
        # Duration
        if duration:
            page.insert_text((230, page_height - 210), duration, fontsize=16)
        
        # Aadhaar
        page.insert_text((187, page_height - 170), aadhaar, fontsize=16)
        
        # Grade
        if grade:
            page.insert_text((680, page_height - 167), grade, fontsize=16)
        
        # Date of Issue
        page.insert_text((470, page_height - 167), doi, fontsize=16)
        
        # Add QR code
        qr_buffer.seek(0)
        qr_rect = fitz.Rect(87, page_height - 87 - 60, 87 + 60, page_height - 87)
        page.insert_image(qr_rect, stream=qr_buffer.read())
        
        # Add photo if provided
        if photo_buffer:
            photo_buffer.seek(0)
            photo_rect = fitz.Rect(
                COORDS['photo']['x'],
                page_height - COORDS['photo']['y'] - COORDS['photo']['height'],
                COORDS['photo']['x'] + COORDS['photo']['width'],
                page_height - COORDS['photo']['y']
            )
            page.insert_image(photo_rect, stream=photo_buffer.read())
        
        # Save PDF to buffer
        pdf_buffer = io.BytesIO()
        doc.save(pdf_buffer)
        doc.close()
        pdf_buffer.seek(0)
        
        # Upload PDF to ImageKit: Generated_Certificates/CERT0001/certificate.pdf
        pdf_upload = upload_to_imagekit(pdf_buffer, "certificate.pdf", cert_id)
        
        if not pdf_upload:
            return jsonify({'error': 'Failed to upload certificate to ImageKit'}), 500
        
        # Upload QR code to ImageKit: Generated_Certificates/CERT0001/qr.png
        qr_buffer.seek(0)
        qr_upload = upload_to_imagekit(qr_buffer, "qr.png", cert_id)
        
        # Save certificate data for verification
        save_certificate_data(cert_id, {
            'name': name,
            'course': course,
            'aadhaar': aadhaar,
            'duration': duration,
            'grade': grade,
            'doi': doi,
            'pdf_url': pdf_upload.get('url', ''),
            'qr_url': qr_upload.get('url', '') if qr_upload else '',
            'created_at': datetime.now().isoformat()
        })
        
        # Save SR number
        save_sr_no(sr_no)
        
        # Return success with download URL
        return jsonify({
            'success': True,
            'cert_id': cert_id,
            'pdf_url': pdf_upload.get('url', ''),
            'verify_url': verify_url,
            'message': f'Certificate {cert_id} generated successfully!'
        })
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/verify/<cert_id>')
def verify_certificate(cert_id):
    # Load certificate data
    all_data = load_certificates_data()
    cert_data = all_data.get(cert_id)
    
    if not cert_data:
        return render_template('verify_not_found.html', cert_id=cert_id)
    
    return render_template('verify.html', 
                          cert_id=cert_id,
                          name=cert_data.get('name', ''),
                          course=cert_data.get('course', ''),
                          aadhaar=cert_data.get('aadhaar', ''),
                          duration=cert_data.get('duration', ''),
                          grade=cert_data.get('grade', ''),
                          doi=cert_data.get('doi', ''),
                          pdf_url=cert_data.get('pdf_url', ''))

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
