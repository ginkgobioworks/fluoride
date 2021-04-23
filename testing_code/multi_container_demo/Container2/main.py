#MICROSERVICE B CODE

from flask import Flask, redirect, jsonify
import json
import urllib
import os

SECRET_STORE = str(os.getenv('fluoride_secrets_manager'))
S3_BUCKET = str(os.getenv('fluoride_s3_bucket'))
PRIMARY_KEY = str(os.getenv('fluoride_dynamodb_table_primary_key'))
DYNAMO_DB = str(os.getenv('fluoride_dynamodb_table'))
REGION = str(os.getenv('fluoride_architecture_region'))
app = Flask(__name__)

@app.route('/')
def main():
    content = urllib.request.urlopen('http://127.0.0.1:80/get_message').read().decode('utf-8')
    return content, 200, {'ContentType': 'application/json'}

@app.route('/get_message')
def message():
    return jsonify({'message': 'Here is a message from microservice 2!'})

@app.route('/healthcheck')
def healthcheck():
    return json.dumps({'success': True}), 200, {'ContentType': 'application/json'}

if __name__ == "__main__":
    app.run(host='0.0.0.0')