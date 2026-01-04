from flask import Flask, render_template, request, jsonify
from PIL import Image
from datetime import datetime
import qrcode
import fitz  # PyMuPDF
import os
import io
import base64
import json
import httpx

app = Flask(__name__)

# ImageKit Configuration
IMAGEKIT_PRIVATE_KEY = os.environ.get('IMAGEKIT_PRIVATE_KEY', 'your_private_key')
IMAGEKIT_URL_ENDPOINT = os.environ.get('IMAGEKIT_URL_ENDPOINT', 'https://ik.imagekit.io/your_id')

# Certificate coordinates
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

COUNTER_FILE = "certificate_counter.json"
DATA_FILE = "certificates_data.json"

def get_next_sr_no():
    if os.path.exists(COUNTER_FILE):
        with open(COUNTER_FILE, 'r') as f:
            data = json.load(f)
            return data.get('next_sr', 1)
    return 1

def save_sr_no(sr_no):
    with open(COUNTER_FILE, 'w') as f:
        json.dump({'next_sr': sr_no + 1}, f)

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

def generate_qr_code(url):
    qr = qrcode.QRCode(version=1, box_size=10, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white")
    img_buffer = io.BytesIO()
    qr_img.save(img_buffer, format='PNG')
    img_buffer.seek(0)
    return img_buffer

def process_photo(photo_data):
    img = Image.open(io.BytesIO(photo_data))
    if img.mode in ('RGBA', 'P'):
        img = img.convert('RGB')
    if img.width > img.height:
        img = img.rotate(-90, expand=True)
    buffer = io.BytesIO()
    img.save(buffer, format='JPEG', quality=95)
    buffer.seek(0)
    return buffer

def upload_to_imagekit(file_buffer, filename, cert_id):
    """Upload file to ImageKit using REST API"""
    try:
        file_buffer.seek(0)
        file_base64 = base64.b64encode(file_buffer.read()).decode('utf-8')
        
        url = "https://upload.imagekit.io/api/v1/files/upload"
        
        data = {
            'file': file_base64,
            'fileName': filename,
            'folder': f'/Generated_Certificates/{cert_id}'
        }
        
        auth = (IMAGEKIT_PRIVATE_KEY, '')
        
        response = httpx.post(url, data=data, auth=auth, timeout=60)
        
        if response.status_code == 200:
            return response.json()
        else:
            print(f"ImageKit error: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        print(f"Upload error: {e}")
        return None

@app.route('/')
def index():
    sr_no = get_next_sr_no()
    return render_template('form.html', sr_no=sr_no, cert_id=f"CERT{sr_no:04d}")

@app.route('/generate', methods=['POST'])
def generate_certificate():
    try:
        name = request.form.get('name', '').strip()
        course = request.form.get('course', '').strip()
        duration = request.form.get('duration', '').strip()
        aadhaar = request.form.get('aadhaar', '').strip()
        grade = request.form.get('grade', '').strip()
        doi = request.form.get('doi', '').strip()
        
        if not all([name, course, aadhaar, doi]):
            return jsonify({'error': 'Please fill all required fields'}), 400
        
        sr_no = get_next_sr_no()
        cert_id = f"CERT{sr_no:04d}"
        
        photo_buffer = None
        if 'photo' in request.files:
            photo_file = request.files['photo']
            if photo_file.filename:
                photo_buffer = process_photo(photo_file.read())
        
        base_url = request.host_url.rstrip('/')
        verify_url = f"{base_url}/verify/{cert_id}"
        
        qr_buffer = generate_qr_code(verify_url)
        
        template_path = "Usdc Certificate.pdf"
        if not os.path.exists(template_path):
            return jsonify({'error': 'Certificate template not found'}), 500
        
        doc = fitz.open(template_path)
        page = doc[0]
        page_height = page.rect.height
        page_width = page.rect.width
        
        # Add text fields
        name_width = fitz.get_text_length(name, fontname="helv", fontsize=16)
        name_x = (page_width - name_width) / 2
        page.insert_text((name_x, page_height - 330), name, fontsize=16)
        page.insert_text((375, page_height - 263), course, fontsize=16)
        if duration:
            page.insert_text((230, page_height - 210), duration, fontsize=16)
        page.insert_text((187, page_height - 170), aadhaar, fontsize=16)
        if grade:
            page.insert_text((680, page_height - 167), grade, fontsize=16)
        page.insert_text((470, page_height - 167), doi, fontsize=16)
        
        # Add QR code
        qr_buffer.seek(0)
        qr_rect = fitz.Rect(87, page_height - 87 - 60, 87 + 60, page_height - 87)
        page.insert_image(qr_rect, stream=qr_buffer.read())
        
        # Add photo
        if photo_buffer:
            photo_buffer.seek(0)
            photo_rect = fitz.Rect(
                COORDS['photo']['x'],
                page_height - COORDS['photo']['y'] - COORDS['photo']['height'],
                COORDS['photo']['x'] + COORDS['photo']['width'],
                page_height - COORDS['photo']['y']
            )
            page.insert_image(photo_rect, stream=photo_buffer.read())
        
        # Save PDF
        pdf_buffer = io.BytesIO()
        doc.save(pdf_buffer)
        doc.close()
        pdf_buffer.seek(0)
        
        # Upload to ImageKit
        pdf_upload = upload_to_imagekit(pdf_buffer, "certificate.pdf", cert_id)
        
        if not pdf_upload:
            return jsonify({'error': 'Failed to upload certificate'}), 500
        
        qr_buffer.seek(0)
        upload_to_imagekit(qr_buffer, "qr.png", cert_id)
        
        # Save data
        save_certificate_data(cert_id, {
            'name': name,
            'course': course,
            'aadhaar': aadhaar,
            'duration': duration,
            'grade': grade,
            'doi': doi,
            'pdf_url': pdf_upload.get('url', ''),
            'created_at': datetime.now().isoformat()
        })
        
        save_sr_no(sr_no)
        
        return jsonify({
            'success': True,
            'cert_id': cert_id,
            'pdf_url': pdf_upload.get('url', ''),
            'verify_url': verify_url,
            'message': f'Certificate {cert_id} generated!'
        })
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/verify/<cert_id>')
def verify_certificate(cert_id):
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
