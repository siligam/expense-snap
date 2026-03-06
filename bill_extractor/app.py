#!/usr/bin/env python3
"""
Bill Extractor web app.
Run with: bill-extractor          (after pip install)
      or: python -m bill_extractor.app
Then open: http://127.0.0.1:5050
"""

import os
import uuid

from flask import Flask, request, jsonify, send_from_directory

from .extract_bill_summary import extract_summary

# index.html lives next to this file inside the package
_PKG_DIR = os.path.dirname(os.path.abspath(__file__))

# Uploads go into the current working directory, not inside the package
UPLOAD_DIR = os.path.join(os.getcwd(), 'uploads')
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = Flask(__name__)


@app.route('/')
def index():
    return send_from_directory(_PKG_DIR, 'index.html')


@app.route('/extract', methods=['POST'])
def extract():
    if 'image' not in request.files:
        return jsonify({'error': 'No image provided'}), 400

    f = request.files['image']
    image_type = request.form.get('image_type', 'auto')

    file_id = str(uuid.uuid4())
    ext = os.path.splitext(f.filename)[1].lower() or '.jpg'
    save_path = os.path.join(UPLOAD_DIR, file_id + ext)
    f.save(save_path)

    try:
        summary = extract_summary(save_path, image_type)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

    return jsonify({
        'file_id': file_id + ext,
        'filename': f.filename,
        'image_url': f'/uploads/{file_id}{ext}',
        'summary': summary,
    })


@app.route('/re-extract', methods=['POST'])
def re_extract():
    data = request.get_json()
    file_id = data.get('file_id')
    image_type = data.get('image_type', 'auto')

    file_path = os.path.join(UPLOAD_DIR, file_id)
    if not os.path.exists(file_path):
        return jsonify({'error': 'File not found'}), 404

    try:
        summary = extract_summary(file_path, image_type)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

    return jsonify({'summary': summary})


@app.route('/uploads/<path:filename>')
def serve_upload(filename):
    return send_from_directory(UPLOAD_DIR, filename)


@app.route('/reset', methods=['POST'])
def reset():
    for fname in os.listdir(UPLOAD_DIR):
        try:
            os.remove(os.path.join(UPLOAD_DIR, fname))
        except OSError:
            pass
    return jsonify({'status': 'ok'})


def main():
    """Entry point for the `bill-extractor` console script."""
    print('\n  Bill Extractor running at http://127.0.0.1:5050\n')
    # use_reloader=False prevents EasyOCR from loading twice in debug mode
    app.run(debug=False, port=5050, host='127.0.0.1', use_reloader=False)


if __name__ == '__main__':
    main()
