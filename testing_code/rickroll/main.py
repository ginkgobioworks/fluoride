import os
from flask import Flask,redirect
import json

app = Flask(__name__)

@app.route('/')
def hello():
    return redirect("https://www.youtube.com/watch?v=dQw4w9WgXcQ", code=302)

@app.route('/healthcheck')
def healthcheck():
    return json.dumps({'success':True}), 200, {'ContentType':'application/json'}

if __name__ == "__main__":
    app.run(host='0.0.0.0')