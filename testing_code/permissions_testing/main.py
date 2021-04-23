import os
from flask import Flask, redirect
import json
import boto3
import shutil
import subprocess
import uuid
import base64
import logging

SECRET_STORE = str(os.getenv('fluoride_secrets_manager'))
S3_BUCKET = str(os.getenv('fluoride_s3_bucket'))
PRIMARY_KEY = str(os.getenv('fluoride_dynamodb_table_primary_key'))
DYNAMO_DB = str(os.getenv('fluoride_dynamodb_table'))
REGION = str(os.getenv('fluoride_architecture_region'))
app = Flask(__name__)

def reconstitute_auths():
    # Create a Secrets Manager client
    session = boto3.session.Session(region_name=REGION)
    client = session.client(
        service_name='secretsmanager'
    )

    try:
        get_secret_value_response = client.get_secret_value(
            SecretId=SECRET_STORE
        )
    except ClientError as e:
        if e.response['Error']['Code'] == 'DecryptionFailureException':
            # Secrets Manager can't decrypt the protected secret text using the provided KMS key.
            # Deal with the exception here, and/or rethrow at your discretion.
            raise e
        elif e.response['Error']['Code'] == 'InternalServiceErrorException':
            # An error occurred on the server side.
            # Deal with the exception here, and/or rethrow at your discretion.
            raise e
        elif e.response['Error']['Code'] == 'InvalidParameterException':
            # You provided an invalid value for a parameter.
            # Deal with the exception here, and/or rethrow at your discretion.
            raise e
        elif e.response['Error']['Code'] == 'InvalidRequestException':
            # You provided a parameter value that is not valid for the current state of the resource.
            # Deal with the exception here, and/or rethrow at your discretion.
            raise e
        elif e.response['Error']['Code'] == 'ResourceNotFoundException':
            # We can't find the resource that you asked for.
            # Deal with the exception here, and/or rethrow at your discretion.
            raise e
    else:
        # change the JSON string into a JSON object
        jsonObject = json.loads(get_secret_value_response['SecretString'])
        for key in jsonObject:
            file = open(key, "wb+")  # append mode
            file.write(base64.b64decode(jsonObject[key].encode('utf8')))
            file.close()
    return


@app.route('/')
def hello():
    # initialize string to report on results
    testing_string = ''

    # get folder uuid
    FOLDER_UUID = str(uuid.uuid4())

    # check that we can reconstitue auths/files from our secrets manager
    os.mkdir(FOLDER_UUID)
    os.chdir(FOLDER_UUID)
    reconstitute_auths()
    os.chdir('..')
    testing_string = testing_string + 'Secrets were succesfully reconstituted!' + '\n'

    # check that we can upload these reconstituted files to our s3 bucket.
    # Upload the file
    try:
        rv = subprocess.check_output("aws s3 cp " + FOLDER_UUID + " s3://" + S3_BUCKET + " --recursive", shell=True)
    except subprocess.CalledProcessError as e:
        output = e.output
        logging.log(level=logging.ERROR, msg=str(output))
        raise RuntimeError("command '{}' return with error (code {}): {}".format(e.cmd, e.returncode, output))
    testing_string = testing_string + 'Successfully uploaded to S3 bucket named ' + S3_BUCKET + '!\n'

    # wipe s3 bucket
    try:
        rv = subprocess.check_output("aws s3 rm" + " s3://" + S3_BUCKET + " --recursive", shell=True)
    except subprocess.CalledProcessError as e:
        output = e.output
        logging.log(level=logging.ERROR, msg=str(output))
        raise RuntimeError("command '{}' return with error (code {}): {}".format(e.cmd, e.returncode, output))
    testing_string = testing_string + 'Successfully wiped S3 bucket named ' + S3_BUCKET + '!\n'

    client = boto3.client("dynamodb")
    dyanmoDB_UUID = str(uuid.uuid4())

    # write to DyanmoDB
    response = client.put_item(
        TableName=DYNAMO_DB,
        Item={
            PRIMARY_KEY: {"S": dyanmoDB_UUID},
        }
    )
    testing_string = testing_string + 'Successfully wrote to DyanmoDB named ' + DYNAMO_DB + '!\n'

    # delete from DyanmoDB
    response = client.delete_item(
        TableName=DYNAMO_DB,
        Key={
            PRIMARY_KEY: {"S": dyanmoDB_UUID},
        }
    )
    testing_string = testing_string + 'Successfully wrote to DyanmoDB named ' + DYNAMO_DB + '!\n'

    #REMOVE FOLDER WITH SECRETS
    shutil.rmtree(FOLDER_UUID)

    #EVERYTHING PASSED!
    testing_string = testing_string + 'Everything is good' + '!\n'
    return json.dumps({'result': testing_string}), 200, {'ContentType': 'application/json'}

@app.route('/healthcheck')
def healthcheck():
    return json.dumps({'success': True}), 200, {'ContentType': 'application/json'}


if __name__ == "__main__":
    app.run(host='0.0.0.0')
