import os
import shutil
import uuid
from subprocess import call, check_output, CalledProcessError
import boto3
import traceback
from boto3.s3.transfer import TransferConfig
import multiprocessing
import base64
import json
from distutils.dir_util import copy_tree
import subprocess
import unicodedata
import re
from awscli.clidriver import create_clidriver
import io
import time
import git
import jinja2
import random

version_number = 1.31

def check_if_list_contains_all_strings_or_lists(lst):
    #takes a list and returns true if all entries are either all lists or are all strs.
    return True if all(isinstance(x, str) for x in lst) or all(isinstance(x, list) for x in lst) else False

def check_all_lists_within_list_are_all_of_uniform_length(lst):
    #takes a list of lists and returns true if they all have the same length else returns false.
    return True if len({len(i) for i in lst}) == 1 else False

def evaluate_string_input(input_string):
    if not ' ' in input_string:
        return input_string #it's not a space separated list
    else:
        return input_string.split(' ') #it is a space separated list so split it

def return_error_string(command,array_of_inputs,array_of_input_names):
    string = 'For the command ' + command + ', the inputs for ' + str(array_of_input_names) + ' must all either all be strings or all be lists of uniform length.' + '\n'

    for i in range(len(array_of_inputs)):
        string = string + '\n'
        string = string + 'The current value for ' + '"' + array_of_input_names[i] + '"' + " is " + str(array_of_inputs[i]) + '.' + '\n'
        string = string + 'It has a datatype of ' + str(type(evaluate_string_input(array_of_inputs[i]))) +'.' + '\n'
        if isinstance(evaluate_string_input(array_of_inputs[i]), list):
            string = string + 'It is a list with a length of ' + str(len(evaluate_string_input(array_of_inputs[i]))) +'.' + '\n'
        else:
            string = string + '\n'

    return string

def parse_potential_array_inputs(command,array_of_inputs,array_of_input_names):

    try:
        #turn string representations of arrays into arrays
        for input_number in range(len(array_of_inputs)):
            array_of_inputs[input_number] = evaluate_string_input(array_of_inputs[input_number])
    except Exception as error:
        print('Could not parse malformed input(s).')
        print(
            'Inputs either must be a string like "baseball" or a space separated list like "baseball bat".')
        print('The following inputs were detected for this command: ' + str(array_of_inputs))
        print('The inputs above were designated for the following input names (in order): ' + str(array_of_input_names))
        print('The following traceback was returned:')
        traceback.print_tb(error.__traceback__)

    #check that all entries in the list are either uniformly lists or uniformly strings.
    if check_if_list_contains_all_strings_or_lists(array_of_inputs):
        pass
    else:
        raise ValueError(return_error_string(command,array_of_inputs,array_of_input_names))

    #if the list contains lists check that they're all the same length
    for input_number in range(len(array_of_inputs)):
        if isinstance(evaluate_string_input(array_of_inputs[input_number]), list):
            if check_all_lists_within_list_are_all_of_uniform_length(array_of_inputs):
                pass
            else:
                raise ValueError(return_error_string(command, array_of_inputs, array_of_input_names))
            inputs_are_lists = True
        else:
            inputs_are_lists = False

    return inputs_are_lists

def parse_inputs(command,minimum_variables_to_be_declared,maximum_variables_to_be_declared,variables_exempt_from_parsing,initial_context,current_context):
    enforce_minimum_variable_declarations(command,minimum_variables_to_be_declared,current_context)
    enforce_maximum_variable_declarations(command,maximum_variables_to_be_declared,variables_exempt_from_parsing,initial_context)
    return 0

def enforce_minimum_variable_declarations(command,minimum_variables_to_be_declared,current_context):
    for variable in minimum_variables_to_be_declared:
        if current_context[variable] == None:
            raise ValueError('For the command ' + '"' + command + '"' + ' the variable ' + '"' + variable + '"' + ' must be given a value. Currently it does not have a value set.')
        else:
            pass

    return 0

def enforce_maximum_variable_declarations(command,maximum_variables_to_be_declared,variables_exempt_from_parsing,initial_context):
    list_of_variables_to_scan = []

    for variable in initial_context.keys():
        if variable == 'command':
            continue
        if variable not in maximum_variables_to_be_declared and variable not in variables_exempt_from_parsing:
            list_of_variables_to_scan.append(variable)
        else:
            pass

    for variable in list_of_variables_to_scan:
        if initial_context[variable] != None:
            raise ValueError('The command ' + '"' + command + '"' + ' has no options for the variable ' + '"' + variable + '"' + ' which should not be set for this command. Currently it has a value of: ' + str(initial_context[variable]) + '.')
        else:
            pass

    return 0

def get_session(region, access_id, secret_key, secret_token = None):
    if not secret_token:
        return boto3.session.Session(region_name=region,
                                    aws_access_key_id=access_id,
                                    aws_secret_access_key=secret_key)
    else:
        return boto3.session.Session(region_name=region,
                                    aws_access_key_id=access_id,
                                    aws_secret_access_key=secret_key,
                                    aws_session_token=secret_token)

def activate_role_vars_if_exists():
    #Get home directory
    home = os.path.expanduser("~")

    #If there's a file named fluoride_cli_role_credentials.txt in the .aws folder in the home directory we're going to continue.
    if os.path.exists(os.path.join(home,'.aws',"fluoride_cli_role_credentials.txt")):
        pass
    else:
        return #The file with our credentials didn't exist so return. No need to actviate any credentials.

    #read lines from file into array
    with open(os.path.join(home,'.aws',"fluoride_cli_role_credentials.txt")) as file:
        array = file.readlines()

    #Parse array for variables
    newsession_id = array[0].strip()
    newsession_key = array[1].strip()
    newsession_token = array[2].strip()

    # SET NEW ENVRIONMENT
    env = os.environ.copy()
    env['LC_CTYPE'] = u'en_US.UTF'
    env['AWS_ACCESS_KEY_ID'] = newsession_id
    env['AWS_SECRET_ACCESS_KEY'] = newsession_key
    env['AWS_SESSION_TOKEN'] = newsession_token
    os.environ.update(env)
    return env

def unset_role_vars_on_error():
    check_output('unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN', shell=True)
    return

def set_role(account_number,role_to_assume_to_target_account,mfa_token,serial_number):

    ACCOUNT_NUMBER = account_number
    IAM_ROLE = role_to_assume_to_target_account

    #Get home directory
    home = os.path.expanduser("~")

    if os.path.exists(os.path.join(home, '.aws')):
        pass
    else:
        raise ValueError('There is no .aws directory in the home directory possibly because the aws cli is not installed. This must be rectified before the set_role command can be used.')

    boto_sts = boto3.client('sts')

    #ASSUME ROLE
    if mfa_token:
        print("RoleArn=" + 'arn:aws:iam::' + ACCOUNT_NUMBER + r':role/' + IAM_ROLE)
        stsresponse = boto_sts.assume_role(
            RoleArn='arn:aws:iam::' + ACCOUNT_NUMBER + r':role/' + IAM_ROLE,
            RoleSessionName=str(uuid.uuid4()),
            SerialNumber=serial_number,
            TokenCode=mfa_token
        )
    else:
        print("RoleArn=" + 'arn:aws:iam::' + ACCOUNT_NUMBER + r':role/' + IAM_ROLE)
        stsresponse = boto_sts.assume_role(
            RoleArn='arn:aws:iam::' + ACCOUNT_NUMBER + r':role/' + IAM_ROLE,
            RoleSessionName=str(uuid.uuid4())
        )

    # Save the details from assumed role into vars
    newsession_id = stsresponse["Credentials"]["AccessKeyId"]
    newsession_key = stsresponse["Credentials"]["SecretAccessKey"]
    newsession_token = stsresponse["Credentials"]["SessionToken"]

    # Write to file
    with open(os.path.join(home,'.aws',"fluoride_cli_role_credentials.txt"),'w+') as file:
        file.write(newsession_id+'\n')
        file.write(newsession_key+'\n')
        file.write(newsession_token+'\n')
        file.write(ACCOUNT_NUMBER+'\n')
        file.write(IAM_ROLE+'\n')

    print('Role successfully set!')
    return

def check_role():
    #Get home directory
    home = os.path.expanduser("~")
    if os.path.exists(os.path.join(home,'.aws',"fluoride_cli_role_credentials.txt")):
        print('Role file is detected. If you suspect this role file is corrupted please consider running "fluoride_cli release_role" to clear the current role file.')
        with open(os.path.join(home, '.aws', "fluoride_cli_role_credentials.txt")) as file:
            array = file.readlines()
        print('Currently assumed role into account ' + array[3].strip() + ' as IAM role named ' + array[4].strip() +'.')
    else:
        print('No role file is detected!')
    return

def release_role():
    #Get home directory
    home = os.path.expanduser("~")
    if os.path.exists(os.path.join(home,'.aws',"fluoride_cli_role_credentials.txt")):
        os.remove(os.path.join(home,'.aws',"fluoride_cli_role_credentials.txt"))
        print('Role released!')
    else:
        print('No role is currently set!')
    return

def check_for_updates():
    try:
        repo = git.Repo(os.path.join(os.path.dirname(os.path.realpath(__file__))), search_parent_directories=True)
    except:
        print('The installation of this CLI located at ' + str(os.path.join(os.path.dirname(os.path.realpath(__file__)))) +' is not inside a Fluoride. The update system relies on this being the case so until this is fixed you will not be able to update your CLI.')
        return 0

    try:
        remote_repo_url = repo.remote("origin").url
    except:
        print('The git repo this installation of the CLI is located in does not have a URL specified for origin. For updates to work this URL must exist and it must be pointed at the Fluoride repo.')
        return 0

    try:
        check_output('git clone ' + str(remote_repo_url),shell=True)
    except:
        print('Could not check for update. No command line access to the fluoride repo in '+str(remote_repo_url)+' was detected.')
        return 0

    f = open("fluoride/cli_version.txt", "r")
    version_number_from_source = float(f.readline().strip())
    if version_number_from_source > version_number:
        print('Version number ' + str(version_number_from_source) + ' is the most up to date version of fluoride_cli. Updating you from your current version of ' +str(version_number) +'.')
        result = subprocess.call('git fetch origin && git reset --hard origin/master && git clean -f -d',cwd=os.path.join(os.path.dirname(os.path.realpath(__file__)),'temp_store','fluoride'),shell=True)
        shutil.move(os.path.join(os.path.dirname(os.path.realpath(__file__)), 'temp_store', 'fluoride', 'fluoride_cli', 'lib.py'),os.path.join(os.path.dirname(os.path.realpath(__file__)), 'lib.py'))
        shutil.move(os.path.join(os.path.dirname(os.path.realpath(__file__)), 'temp_store', 'fluoride', 'fluoride_cli', 'cli.py'),os.path.join(os.path.dirname(os.path.realpath(__file__)), 'cli.py'))
        print('Upgrade completed!')
        print('You are now running version '+str(version_number_from_source)+' which is the most up to date version of fluoride_cli! Congrats!')
    else:
        result = subprocess.call('git fetch origin && git reset --hard origin/master && git clean -f -d',cwd=os.path.join(os.path.dirname(os.path.realpath(__file__)),'temp_store','fluoride'),shell=True)
        print('You are running version '+str(version_number)+' which is the most up to date version of fluoride_cli! Congrats!')
    shutil.rmtree(os.path.join(os.path.dirname(os.path.realpath(__file__)),'temp_store'))
    return 0

def check_for_environment_variables(account_number, role_to_assume_to_target_account, local_image_to_push, path_to_docker_folder, ecr_repo_to_push_to, cloudformation_of_architecture, ecr_repo_to_make, path_to_local_secrets, secret_store):
    if os.path.exists(os.path.join(os.path.dirname(os.path.realpath(__file__)), 'current_fluoride_profile_config.txt')):
        with open(os.path.join(os.path.dirname(os.path.realpath(__file__)), 'current_fluoride_profile_config.txt'),
                  'r') as config_file:
            current_profile = config_file.read().strip()
    else:
        return account_number, role_to_assume_to_target_account, local_image_to_push, path_to_docker_folder, ecr_repo_to_push_to, cloudformation_of_architecture, ecr_repo_to_make, path_to_local_secrets, secret_store #no profile was set!

    profile_not_found = True
    for file in os.listdir(os.path.join(os.path.dirname(os.path.realpath(__file__)))):
        if file not in ['lib.py', 'cli.py' ,'.DS_Store','__init__.py','__pycache__','fluoride','temp_store','current_fluoride_profile_config.txt']:
            if file == current_profile:
                profile_not_found = False

    if profile_not_found:
        print('Profile named ' + current_profile + ' pointed at in current_fluoride_profile_config.txt was not detected in the list of available profiles.')
        print('Here is a list of profiles we have detected:')
        print('######PROFILE LIST START########')

        for file in os.listdir(os.path.join(os.path.dirname(os.path.realpath(__file__)))):
            if file not in ['lib.py', 'cli.py' ,'.DS_Store','__init__.py','__pycache__','fluoride','temp_store','current_fluoride_profile_config.txt']:
                print(file)

        print('######PROFILE LIST END########')
        print('Please rectify the problem either programmatically using the CLI or by configuring files manually in the following directory: ' + str(os.path.join(os.path.dirname(os.path.realpath(__file__)))))
        print('Until the problem is rectified you will not be able to access environment variables stored in profile files and default values for inputs will be returned.')
        return account_number, role_to_assume_to_target_account, path_to_docker_folder, ecr_repo_to_push_to, path_to_local_folder_to_batch, s3_bucket_to_upload_to, dynamo_db_to_query, cloudformation_of_architecture, path_to_local_secrets, secret_store, s3_bucket_for_results, directory_to_sync_s3_bucket_to

    with open(os.path.join(os.path.dirname(os.path.realpath(__file__)), current_profile), 'r') as profile_file:
        data = json.loads(profile_file.read())

    if account_number == None:
        try:
            account_number = str(data['fluoride_cli_account_number'])
        except:
            account_number = None

    if role_to_assume_to_target_account == None:
        try:
            role_to_assume_to_target_account = str(data['fluoride_cli_role_to_assume_to_target_account'])
        except:
            role_to_assume_to_target_account = None

    if local_image_to_push == None:
        try:
            local_image_to_push = str(data['fluoride_cli_local_image_to_push'])
        except:
            local_image_to_push = None

    if path_to_docker_folder == None:
        try:
            path_to_docker_folder = str(data['fluoride_cli_path_to_docker_folder'])
        except:
            path_to_docker_folder = None

    if ecr_repo_to_push_to == None:
        try:
            ecr_repo_to_push_to = str(data['fluoride_cli_ecr_repo_to_push_to'])
        except:
            ecr_repo_to_push_to = None

    if cloudformation_of_architecture == None:
        try:
            cloudformation_of_architecture = str(data['fluoride_cli_cloudformation_of_architecture'])
        except:
            cloudformation_of_architecture = None

    if ecr_repo_to_make == None:
        try:
            ecr_repo_to_make = str(data['fluoride_cli_ecr_repo_to_make'])
        except:
            ecr_repo_to_make = None

    if path_to_local_secrets == None:
        try:
            path_to_local_secrets = str(data['fluoride_cli_path_to_local_secrets'])
        except:
            path_to_local_secrets = None

    if secret_store == None:
        try:
            secret_store = str(data['fluoride_cli_secret_store'])
        except:
            secret_store = None

    return account_number, role_to_assume_to_target_account, local_image_to_push, path_to_docker_folder, ecr_repo_to_push_to, cloudformation_of_architecture, ecr_repo_to_make, path_to_local_secrets, secret_store

######################################################GENERATE MULTICONTAINER CLOUDFORMAITON LIBRARIES START HERE######################################################
def attempt_to_fetch_latest_template(path_to_template_file):
    try:
        #attempt to update
        print('Attempting to fetch latest version of fluoride.j2 template from git repo ...')
        try:
            repo = git.Repo(os.path.join(os.path.dirname(os.path.realpath(__file__))), search_parent_directories=True)
        except:
            print('The installation of this CLI located at ' + str(os.path.join(os.path.dirname(os.path.realpath(__file__)))) +' is not inside a Fluoride. The update system relies on this being the case so until this is fixed you will not be able to fetch the latest version of the template this command uses.')
            return 0

        #get remote repo url
        try:
            remote_repo_url = repo.remote("origin").url
        except:
            print(
                'The git repo this installation of the CLI is located in does not have a URL specified for origin. For fetching the latest template to work this URL must exist and it must be pointed at the Fluoride repo.')
            return 0

        #clone the source repo from origin
        try:
            check_output('git clone ' + str(remote_repo_url), shell=True)
        except:
            print('Could not check for latest version of template. No command line access to the fluoride repo in ' + str(remote_repo_url) + ' was detected.')
            return 0

        #update the cached files if the one from the repo is any different
        try:
            shutil.copy2(os.path.join(os.path.dirname(os.path.realpath(__file__)),'temp_store','fluoride','templates','fluoride.j2'), path_to_template_file)
            print("Update complete! You are now using the most up to date version of the Fluoride template!")

            # If source and destination are same
        except shutil.SameFileError:
            print("Congratulations you were already using the most up to date version of the template!")

            # If there is any permission issue
        except PermissionError:
            print("Permission denied. Could not update the template located at " + path_to_template_file + ' because this CLI lacks the permission to write to that file.')

            # For other errors
        except:
            print("Error occurred while copying file from temporary storage to " + path_to_template_file + " with the following traceback:")
            traceback.print_tb(error.__traceback__)

        #clean up temporary storage dir
        shutil.rmtree(os.path.join(os.path.dirname(os.path.realpath(__file__)), 'temp_store'))
    except Exception as error:
        print('Update failed with the following error:')
        traceback.print_tb(error.__traceback__)
        print('Attempting to use cached version of the fluoride.j2 template!')
    return

def generate_multicontainer_cloudformation(directory_path,output_path,number_of_images):
    try:
        #test that we can write to output path supplied by user
        try:
            with open(output_path, 'w+') as tempfile:  # OSError if file exists or is invalid
                pass
        except OSError:
            raise ValueError('The output_path supplied of ' + output_path + ' is not a writeable output path! We could not create a temporary file there because we lack permissions to do so or because the path was invalid.')

        #check that the argument provided for number_of_images is in fact a string representation of an integer that is greater than or equal to 1
        try:
            int(number_of_images)
            if int(number_of_images) < 1:
                raise ValueError('The number of images supplied must be 1 or greater!')
        except ValueError:
            raise ValueError('The argument provided for number_of_images of ' + number_of_images + ' is not a string representation of an integer!')

        template_folder = os.path.join(os.path.dirname(directory_path),'templates')
        path_to_template_file = os.path.join(template_folder,'fluoride.j2')

        #attempt to update template file with latest file from git repo
        attempt_to_fetch_latest_template(path_to_template_file)

        # check for the existence of the fluoride template file in the templates folder that came with the git repo
        if not os.path.isfile(path_to_template_file):
            raise ValueError('The fluoride.j2 template file from the Fluoride repo was not found at ' + os.path.join(template_folder,'fluoride.j2'))
        else:
            pass #there's a file named 'fluoride.j2' where we thought it would be. which is a good thing.

        # let's get to rendering!
        with open(path_to_template_file) as template_file:
            template = jinja2.Template(template_file.read())

        output_template_data = template.render(image_number=range(1,int(number_of_images)+1))

        #write to file!
        with open(output_path, "w+") as output_fh:
            output_fh.write(output_template_data)

        print('Successfully wrote Fluoride cloudformation for ' + str(number_of_images) + ' container tasks to ' + output_path)

    except Exception as error:
        traceback.print_tb(error.__traceback__)
        raise ValueError(str(error))
    return
######################################################GENERATE MULTICONTAINER CLOUDFORMAITON LIBRARIES END HERE######################################################


######################################################MAKE ECR REPO LIBRARIES START HERE######################################################
def make_ecr_repo(account_number,role_to_assume_to_target_account,ecr_repo_to_make,dont_assume,mfa_token,serial_number,inputs_are_lists):
    region = check_output('aws configure get region',shell=True).strip().decode("utf-8")
    ACCOUNT_NUMBER = account_number
    IAM_ROLE = role_to_assume_to_target_account
    NEW_CONTAINER_NAME = ecr_repo_to_make

    activate_role_vars_if_exists()

    # where the ECR repo creation happens
    ##################################################################################################################
    try:
        if dont_assume == 'False':
            boto_sts = boto3.client('sts')

            if mfa_token:
                print("RoleArn=" + 'arn:aws:iam::' + ACCOUNT_NUMBER + r':role/' + IAM_ROLE)
                stsresponse = boto_sts.assume_role(
                    RoleArn='arn:aws:iam::' + ACCOUNT_NUMBER + r':role/' + IAM_ROLE,
                    RoleSessionName=str(uuid.uuid4()),
                    SerialNumber=serial_number,
                    TokenCode=mfa_token
                )
            else:
                print("RoleArn=" + 'arn:aws:iam::' + ACCOUNT_NUMBER + r':role/' + IAM_ROLE)
                stsresponse = boto_sts.assume_role(
                    RoleArn='arn:aws:iam::' + ACCOUNT_NUMBER + r':role/' + IAM_ROLE,
                    RoleSessionName=str(uuid.uuid4())
                )

            # Save the details from assumed role into vars
            newsession_id = stsresponse["Credentials"]["AccessKeyId"]
            newsession_key = stsresponse["Credentials"]["SecretAccessKey"]
            newsession_token = stsresponse["Credentials"]["SessionToken"]

            # Here I create an ecr client using the assumed creds.
            ecr_assumed_client = get_session(
                region,
                newsession_id,
                newsession_key,
                newsession_token
            ).client('ecr')
        else:
            # Here I create an ecr client using the envrionment creds.
            ecr_assumed_client = boto3.session.Session(region_name=region).client('ecr')

        if inputs_are_lists:
            ecr_repo_to_make = evaluate_string_input(ecr_repo_to_make)
            for i in range(len(ecr_repo_to_make)):
                try:
                    response = ecr_assumed_client.create_repository(repositoryName=ecr_repo_to_make[i],
                                                                    encryptionConfiguration={'encryptionType': 'AES256'})
                    print('Successfully submitted call to create repository. Here is the result of our call: ')
                    print(response)
                except:
                    traceback.print_exc()
        else:
            response = ecr_assumed_client.create_repository(repositoryName=NEW_CONTAINER_NAME,encryptionConfiguration={'encryptionType': 'AES256'})
            print('Successfully submitted call to create repository. Here is the result of our call: ')
            print(response)

    except Exception as error:
        traceback.print_tb(error.__traceback__)
        raise ValueError(str(error))
    return
######################################################MAKE ECR REPO LIBRARIES END HERE######################################################

######################################################ECR PUSH LIBRARIES START HERE######################################################
def slugify(slug):
	slug = unicodedata.normalize('NFKD', slug)
	slug = str(slug.encode('ascii', 'ignore').lower())
	slug = re.sub(r'[^a-z0-9]+', '-', slug).strip('-')
	slugified_slug = str(re.sub(r'[-]+', '-', slug))
	slugified_slug = (slugified_slug[:250] + '..') if len(slugified_slug) > 250 else slugified_slug
	return slugified_slug

def build_container(path_to_docker_folder):
    current_dir = os.getcwd()
    os.chdir(path_to_docker_folder)

    try:
        result = subprocess.call('docker build --no-cache -f Dockerfile.txt -t '+slugify(path_to_docker_folder)+':latest .',shell=True)

        if result != 0:
            os.chdir(current_dir)
            raise ValueError('Docker build command failed. Could not build initial worker container. Process is being aborted.')

    except:
        try:
            result = subprocess.call('docker build --no-cache -f Dockerfile -t '+slugify(path_to_docker_folder)+':latest .',shell=True)

            if result != 0:
                os.chdir(current_dir)
                raise ValueError('Docker build command failed. Could not build initial worker container. Process is being aborted.')

        except Exception as error:
            traceback.print_tb(error.__traceback__)
            print('Could not deploy. Docker was not properly configured or no file named "Dockerfile.txt" or "Dockerfile" was found in the path to deploy from.')
            os.chdir(current_dir)
            raise ValueError(str(error))

    return 0

def push_existing_image_to_ecr(account_number,role_to_assume_to_target_account,ecr_repo_to_push_to,local_image_to_push,dont_assume,mfa_token,serial_number,inputs_are_lists):
    region = check_output('aws configure get region',shell=True).strip().decode("utf-8")
    ACCOUNT_NUMBER = account_number
    IAM_ROLE = role_to_assume_to_target_account
    REPOSITORY_URL = ACCOUNT_NUMBER + r'.dkr.ecr.'+region+'.amazonaws.com/'  # should end in a slash
    DESTINATION_CONTAINER_NAME = ecr_repo_to_push_to

    activate_role_vars_if_exists()

    # where the programmatic push to ECR repo happens
    ##################################################################################################################
    if dont_assume == 'False':
        boto_sts = boto3.client('sts')

        if mfa_token:
            print("RoleArn=" + 'arn:aws:iam::' + ACCOUNT_NUMBER + r':role/' + IAM_ROLE)
            stsresponse = boto_sts.assume_role(
                RoleArn='arn:aws:iam::' + ACCOUNT_NUMBER + r':role/' + IAM_ROLE,
                RoleSessionName=str(uuid.uuid4()),
                SerialNumber=serial_number,
                TokenCode=mfa_token
            )
        else:
            print("RoleArn=" + 'arn:aws:iam::' + ACCOUNT_NUMBER + r':role/' + IAM_ROLE)
            stsresponse = boto_sts.assume_role(
                RoleArn='arn:aws:iam::' + ACCOUNT_NUMBER + r':role/' + IAM_ROLE,
                RoleSessionName=str(uuid.uuid4())
            )

        # Save the details from assumed role into vars
        newsession_id = stsresponse["Credentials"]["AccessKeyId"]
        newsession_key = stsresponse["Credentials"]["SecretAccessKey"]
        newsession_token = stsresponse["Credentials"]["SessionToken"]

        # Here I create an ecr client using the assumed creds.
        ecr_assumed_client = get_session(
            region,
            newsession_id,
            newsession_key,
            newsession_token
        ).client('ecr')
    else:
        # Here I create an ecr client using the envrionment creds.
        ecr_assumed_client = boto3.session.Session(region_name=region).client('ecr')

    if inputs_are_lists:
        ecr_repo_to_push_to = evaluate_string_input(ecr_repo_to_push_to)
        local_image_to_push = evaluate_string_input(local_image_to_push)
        for i in range(len(ecr_repo_to_push_to)):
            # get authorization token
            response = ecr_assumed_client.get_authorization_token(
                registryIds=[
                    ACCOUNT_NUMBER,
                ]
            )

            # GET READY TO MOVE THINGS
            folder_that_contains_this_script = os.path.dirname(os.path.realpath(__file__))
            os.chdir(folder_that_contains_this_script)

            # get auth token
            auth_token = base64.b64decode(response['authorizationData'][0]['authorizationToken']).decode("utf-8")[
                         4:]  # CUT OFF THE INITIAL AWS!

            # push the recently built image
            subprocess.call(r"docker login -u AWS -p " + auth_token + " " + REPOSITORY_URL, shell=True)
            subprocess.call(r"docker tag " + local_image_to_push[i] + " " + REPOSITORY_URL + ecr_repo_to_push_to[i],
                            shell=True)
            subprocess.call("docker push " + REPOSITORY_URL + ecr_repo_to_push_to[i], shell=True)
    else:
        # get authorization token
        response = ecr_assumed_client.get_authorization_token(
            registryIds=[
                ACCOUNT_NUMBER,
            ]
        )

        #GET READY TO MOVE THINGS
        folder_that_contains_this_script = os.path.dirname(os.path.realpath(__file__))
        os.chdir(folder_that_contains_this_script)

        #get auth token
        auth_token = base64.b64decode(response['authorizationData'][0]['authorizationToken']).decode("utf-8")[4:] #CUT OFF THE INITIAL AWS!

        #push the recently built image
        subprocess.call(r"docker login -u AWS -p "+auth_token+" "+REPOSITORY_URL,shell=True)
        subprocess.call(r"docker tag "+local_image_to_push+" "+REPOSITORY_URL+DESTINATION_CONTAINER_NAME,shell=True)
        subprocess.call("docker push "+REPOSITORY_URL+DESTINATION_CONTAINER_NAME,shell=True)

    return 0

def push_to_ecr(account_number,ecr_assumed_client,ecr_repo_to_push_to,path_to_docker_folder):
    region = check_output('aws configure get region',shell=True).strip().decode("utf-8")
    ACCOUNT_NUMBER = account_number
    REPOSITORY_URL = ACCOUNT_NUMBER + r'.dkr.ecr.'+region+'.amazonaws.com/'  # should end in a slash
    DESTINATION_CONTAINER_NAME = ecr_repo_to_push_to

    # get authorization token
    response = ecr_assumed_client.get_authorization_token(
        registryIds=[
            ACCOUNT_NUMBER,
        ]
    )

    #GET READY TO MOVE THINGS
    folder_that_contains_this_script = os.path.dirname(os.path.realpath(__file__))
    os.chdir(folder_that_contains_this_script)

    #get auth token
    auth_token = base64.b64decode(response['authorizationData'][0]['authorizationToken']).decode("utf-8")[4:] #CUT OFF THE INITIAL AWS!

    #push the recently built image
    subprocess.call(r"docker login -u AWS -p "+auth_token+" "+REPOSITORY_URL,shell=True)
    subprocess.call(r"docker tag "+slugify(path_to_docker_folder)+":latest "+REPOSITORY_URL+DESTINATION_CONTAINER_NAME,shell=True)
    subprocess.call("docker push "+REPOSITORY_URL+DESTINATION_CONTAINER_NAME,shell=True)

    return 0

def build_and_push_image_to_ecr(account_number,role_to_assume_to_target_account,path_to_docker_folder,ecr_repo_to_push_to,dont_assume,mfa_token,serial_number,inputs_are_lists):

    region = check_output('aws configure get region',shell=True).strip().decode("utf-8")
    ACCOUNT_NUMBER = account_number
    IAM_ROLE = role_to_assume_to_target_account

    activate_role_vars_if_exists()

    # where the programmatic push to ECR repo happens
    ##################################################################################################################
    if dont_assume == 'False':
        boto_sts = boto3.client('sts')

        if mfa_token:
            print("RoleArn=" + 'arn:aws:iam::' + ACCOUNT_NUMBER + r':role/' + IAM_ROLE)
            stsresponse = boto_sts.assume_role(
                RoleArn='arn:aws:iam::' + ACCOUNT_NUMBER + r':role/' + IAM_ROLE,
                RoleSessionName=str(uuid.uuid4()),
                SerialNumber=serial_number,
                TokenCode=mfa_token
            )
        else:
            print("RoleArn=" + 'arn:aws:iam::' + ACCOUNT_NUMBER + r':role/' + IAM_ROLE)
            stsresponse = boto_sts.assume_role(
                RoleArn='arn:aws:iam::' + ACCOUNT_NUMBER + r':role/' + IAM_ROLE,
                RoleSessionName=str(uuid.uuid4())
            )

        # Save the details from assumed role into vars
        newsession_id = stsresponse["Credentials"]["AccessKeyId"]
        newsession_key = stsresponse["Credentials"]["SecretAccessKey"]
        newsession_token = stsresponse["Credentials"]["SessionToken"]

        # Here I create an ecr client using the assumed creds.
        ecr_assumed_client = get_session(
            region,
            newsession_id,
            newsession_key,
            newsession_token
        ).client('ecr')
    else:
        # Here I create an ecr client using the envrionment creds.
        ecr_assumed_client = boto3.session.Session(region_name=region).client('ecr')

    if inputs_are_lists:
        path_to_docker_folder = evaluate_string_input(path_to_docker_folder)
        ecr_repo_to_push_to = evaluate_string_input(ecr_repo_to_push_to)
        for i in range(len(path_to_docker_folder)):
            print('building user provided container located at ' + path_to_docker_folder[i] + ' ...')
            try:
                build_container(path_to_docker_folder[i])
            except Exception as error:
                traceback.print_tb(error.__traceback__)
                print('building fluoride style nested container failed')
                raise ValueError(str(error))
            print('building fluoride style nested container succeeded')

            print('pushing ECR to target container named ' + ecr_repo_to_push_to[i] + '...')
            try:
                push_to_ecr(account_number, ecr_assumed_client, ecr_repo_to_push_to[i], path_to_docker_folder[i])
            except Exception as error:
                traceback.print_tb(error.__traceback__)
                print('pushing container to target ECR repo named ' + ecr_repo_to_push_to[i] + ' failed')
                raise ValueError(str(error))
            print('pushing container to target ECR repo named ' + ecr_repo_to_push_to[i] + ' succeeded')
    else:
        print('building user provided container located at ' + path_to_docker_folder + ' ...')
        try:
            build_container(path_to_docker_folder)
        except Exception as error:
            traceback.print_tb(error.__traceback__)
            print('building fluoride style nested container failed')
            raise ValueError(str(error))
        print('building fluoride style nested container succeeded')

        print('pushing ECR to target container named ' +ecr_repo_to_push_to+'...')
        try:
            push_to_ecr(account_number,ecr_assumed_client,ecr_repo_to_push_to,path_to_docker_folder)
        except Exception as error:
            traceback.print_tb(error.__traceback__)
            print('pushing container to target ECR repo named ' +ecr_repo_to_push_to+' failed')
            raise ValueError(str(error))
        print('pushing container to target ECR repo named ' +ecr_repo_to_push_to+' succeeded')
    return
######################################################ECR PUSH LIBRARIES END HERE######################################################

######################################################UPDATE STACK LIBRARIES START HERE######################################################

def update_stack(account_number,role_to_assume_to_target_account,cloudformation_of_architecture,dont_assume,mfa_token,serial_number):

    activate_role_vars_if_exists()

    try:
        region = check_output('aws configure get region', shell=True).strip().decode("utf-8")
        ACCOUNT_NUMBER = account_number
        IAM_ROLE = role_to_assume_to_target_account
        UUID = str(uuid.uuid4())

        # where the programmatic cloudformation query happens
        ##################################################################################################################
        if dont_assume == 'False':
            boto_sts = boto3.client('sts')

            if mfa_token:
                print("RoleArn=" + 'arn:aws:iam::' + ACCOUNT_NUMBER + r':role/' + IAM_ROLE)
                stsresponse = boto_sts.assume_role(
                    RoleArn='arn:aws:iam::' + ACCOUNT_NUMBER + r':role/' + IAM_ROLE,
                    RoleSessionName=str(uuid.uuid4()),
                    SerialNumber=serial_number,
                    TokenCode=mfa_token
                )
            else:
                print("RoleArn=" + 'arn:aws:iam::' + ACCOUNT_NUMBER + r':role/' + IAM_ROLE)
                stsresponse = boto_sts.assume_role(
                    RoleArn='arn:aws:iam::' + ACCOUNT_NUMBER + r':role/' + IAM_ROLE,
                    RoleSessionName=str(uuid.uuid4())
                )

            # Save the details from assumed role into vars
            newsession_id = stsresponse["Credentials"]["AccessKeyId"]
            newsession_key = stsresponse["Credentials"]["SecretAccessKey"]
            newsession_token = stsresponse["Credentials"]["SessionToken"]

            # Here I create a cloudformation client using the assumed creds.
            assumed_session = get_session(
                region,
                newsession_id,
                newsession_key,
                newsession_token
            )

        else:
            # Here I create a cloudformation client using environment creds.
            assumed_session = boto3.session.Session(region_name=region).client('cloudformation')

        cloudformation_assumed_client = assumed_session.client('cloudformation')
        response = cloudformation_assumed_client.describe_stacks(StackName=cloudformation_of_architecture)
        for key_value_pair in response["Stacks"][0]["Outputs"]:
            if key_value_pair["OutputKey"] == 'Cluster':
                cluster_name = key_value_pair["OutputValue"]
            if key_value_pair["OutputKey"] == 'ServiceName':
                service_name = key_value_pair["OutputValue"]

        print('Found cloudformation and pulled variables for service and cluster name.')
        ecs_assumed_client = assumed_session.client('ecs')

        print('Updating architecture stack now.')
        response = ecs_assumed_client.update_service(cluster=cluster_name,service=service_name,forceNewDeployment=True)

        print('Update command successfully submitted. Here is the output from our command:')
        print(response)
    except Exception as error:
        traceback.print_tb(error.__traceback__)
        raise ValueError(str(error))
    return
######################################################UPDATE STACK LIBRARIES END HERE######################################################

######################################################CHECK HEALTH LIBRARIES START HERE######################################################

def check_health(account_number,role_to_assume_to_target_account,cloudformation_of_architecture,dont_assume,mfa_token,serial_number):

    activate_role_vars_if_exists()

    try:
        region = check_output('aws configure get region', shell=True).strip().decode("utf-8")
        ACCOUNT_NUMBER = account_number
        IAM_ROLE = role_to_assume_to_target_account
        UUID = str(uuid.uuid4())

        # where the programmatic cloudformation query happens
        ##################################################################################################################
        if dont_assume == 'False':
            boto_sts = boto3.client('sts')

            if mfa_token:
                print("RoleArn=" + 'arn:aws:iam::' + ACCOUNT_NUMBER + r':role/' + IAM_ROLE)
                stsresponse = boto_sts.assume_role(
                    RoleArn='arn:aws:iam::' + ACCOUNT_NUMBER + r':role/' + IAM_ROLE,
                    RoleSessionName=str(uuid.uuid4()),
                    SerialNumber=serial_number,
                    TokenCode=mfa_token
                )
            else:
                print("RoleArn=" + 'arn:aws:iam::' + ACCOUNT_NUMBER + r':role/' + IAM_ROLE)
                stsresponse = boto_sts.assume_role(
                    RoleArn='arn:aws:iam::' + ACCOUNT_NUMBER + r':role/' + IAM_ROLE,
                    RoleSessionName=str(uuid.uuid4())
                )

            # Save the details from assumed role into vars
            newsession_id = stsresponse["Credentials"]["AccessKeyId"]
            newsession_key = stsresponse["Credentials"]["SecretAccessKey"]
            newsession_token = stsresponse["Credentials"]["SessionToken"]

            # Here I create a cloudformation client using the assumed creds.
            assumed_session = get_session(
                region,
                newsession_id,
                newsession_key,
                newsession_token
            )

        else:
            # Here I create a cloudformation client using environment creds.
            assumed_session = boto3.session.Session(region_name=region).client('cloudformation')

        cloudformation_assumed_client = assumed_session.client('cloudformation')
        response = cloudformation_assumed_client.describe_stacks(StackName=cloudformation_of_architecture)
        for key_value_pair in response["Stacks"][0]["Outputs"]:
            if key_value_pair["OutputKey"] == 'TargetGroupARN':
                TargetGroupARN = key_value_pair["OutputValue"]

        print('Found cloudformation and pulled variable for TargetGroupARN.')
        elbv2_assumed_client = assumed_session.client('elbv2')

        print('Querying health now.')
        response = elbv2_assumed_client.describe_target_health(TargetGroupArn=TargetGroupARN)

        print('Health query successfully submitted. Here is the output from our command:')
        print(response)
    except Exception as error:
        traceback.print_tb(error.__traceback__)
        raise ValueError(str(error))
    return
######################################################CHECK HEALTH LIBRARIES END HERE######################################################

######################################################DESCRIBE LIBRARIES START HERE######################################################
def describe(account_number,role_to_assume_to_target_account,cloudformation_of_architecture,dont_assume,mfa_token,serial_number):
    print('attempting to describe stack named ' + cloudformation_of_architecture + '...')

    activate_role_vars_if_exists()

    try:
        region = check_output('aws configure get region', shell=True).strip().decode("utf-8")
        ACCOUNT_NUMBER = account_number
        IAM_ROLE = role_to_assume_to_target_account

        # where the programmatic cloudformation query happens
        ##################################################################################################################
        if dont_assume == 'False':
            boto_sts = boto3.client('sts')

            if mfa_token:
                print("RoleArn=" + 'arn:aws:iam::' + ACCOUNT_NUMBER + r':role/' + IAM_ROLE)
                stsresponse = boto_sts.assume_role(
                    RoleArn='arn:aws:iam::' + ACCOUNT_NUMBER + r':role/' + IAM_ROLE,
                    RoleSessionName=str(uuid.uuid4()),
                    SerialNumber=serial_number,
                    TokenCode=mfa_token
                )
            else:
                print("RoleArn=" + 'arn:aws:iam::' + ACCOUNT_NUMBER + r':role/' + IAM_ROLE)
                stsresponse = boto_sts.assume_role(
                    RoleArn='arn:aws:iam::' + ACCOUNT_NUMBER + r':role/' + IAM_ROLE,
                    RoleSessionName=str(uuid.uuid4())
                )

            # Save the details from assumed role into vars
            newsession_id = stsresponse["Credentials"]["AccessKeyId"]
            newsession_key = stsresponse["Credentials"]["SecretAccessKey"]
            newsession_token = stsresponse["Credentials"]["SessionToken"]

            # Here I create a cloudformation client using the assumed creds.
            cloudformation_assumed_client = get_session(
                region,
                newsession_id,
                newsession_key,
                newsession_token
            ).client('cloudformation')
        else:
            # Here I create a cloudformation client using environment creds.
            cloudformation_assumed_client = boto3.session.Session(region_name=region).client('cloudformation')

        response = cloudformation_assumed_client.describe_stacks(StackName=cloudformation_of_architecture)

        print(response)

    except Exception as error:
        traceback.print_tb(error.__traceback__)
        print('attempt to describe stack named ' + cloudformation_of_architecture + ' failed.')
        raise ValueError(str(error))
    print('attempt to describe stack named ' + cloudformation_of_architecture + ' succeeded. The response from the cloudformation client has been returned.')
    return response
######################################################DESCRIBE LIBRARIES STOP HERE######################################################

######################################################SECRETIFY LIBRARIES START HERE######################################################
def secretify(account_number,role_to_assume_to_target_account,path_to_local_secrets,secret_store,dont_assume,mfa_token,serial_number):
    print('attempting to deploy secrets located in ' + path_to_local_secrets + ' to ' + secret_store + '...')

    activate_role_vars_if_exists()

    try:
        region = check_output('aws configure get region', shell=True).strip().decode("utf-8")
        ACCOUNT_NUMBER = account_number
        IAM_ROLE = role_to_assume_to_target_account

        # where the programmatic secrets manager upload happens
        ##################################################################################################################
        if dont_assume == 'False':
            boto_sts = boto3.client('sts')

            if mfa_token:
                print("RoleArn=" + 'arn:aws:iam::' + ACCOUNT_NUMBER + r':role/' + IAM_ROLE)
                stsresponse = boto_sts.assume_role(
                    RoleArn='arn:aws:iam::' + ACCOUNT_NUMBER + r':role/' + IAM_ROLE,
                    RoleSessionName=str(uuid.uuid4()),
                    SerialNumber=serial_number,
                    TokenCode=mfa_token
                )
            else:
                print("RoleArn=" + 'arn:aws:iam::' + ACCOUNT_NUMBER + r':role/' + IAM_ROLE)
                stsresponse = boto_sts.assume_role(
                    RoleArn='arn:aws:iam::' + ACCOUNT_NUMBER + r':role/' + IAM_ROLE,
                    RoleSessionName=str(uuid.uuid4())
                )

            # Save the details from assumed role into vars
            newsession_id = stsresponse["Credentials"]["AccessKeyId"]
            newsession_key = stsresponse["Credentials"]["SecretAccessKey"]
            newsession_token = stsresponse["Credentials"]["SessionToken"]

            # Here I create a s3 client using the assumed creds.
            secretsmanager_assumed_client = get_session(
                region,
                newsession_id,
                newsession_key,
                newsession_token
            ).client('secretsmanager')
        else:
            # Here I create a s3 client using environment creds.
            secretsmanager_assumed_client = boto3.session.Session(region_name=region).client('secretsmanager')

        secrets_dictionary = {}

        #Get new secrets string from directory of secrets
        for item in os.listdir(path_to_local_secrets):
            if os.path.isfile(os.path.join(path_to_local_secrets, item)):
                data = base64.b64encode(open(os.path.join(path_to_local_secrets,item), 'rb').read()).decode('utf-8')
                secrets_dictionary[item] = data


        if not secrets_dictionary:
            print('There were no files in that directory to upload! No action was performed.')
            return

        response = secretsmanager_assumed_client.update_secret(
            SecretId=secret_store,
            SecretString=json.dumps(secrets_dictionary),
        )

        print(response)

    except Exception as error:
        traceback.print_tb(error.__traceback__)
        print('attempt to deploy secrets located in ' + path_to_local_secrets + ' to ' + secret_store + ' failed.')
        raise ValueError(str(error))
    print('attempt to deploy secrets located in ' + path_to_local_secrets + ' to ' + secret_store + ' succeeded.')
    return
######################################################SECRETIFY LIBRARIES STOP HERE######################################################

######################################################EXECUTE COMMAND LIBRARIES START HERE######################################################

def execute_command(account_number,role_to_assume_to_target_account,cloudformation_of_architecture,dont_assume,mfa_token,serial_number,container,command):

    activate_role_vars_if_exists()

    try:
        region = check_output('aws configure get region', shell=True).strip().decode("utf-8")
        ACCOUNT_NUMBER = account_number
        IAM_ROLE = role_to_assume_to_target_account
        UUID = str(uuid.uuid4())

        # where the programmatic cloudformation query happens
        ##################################################################################################################
        if dont_assume == 'False':
            boto_sts = boto3.client('sts')

            if mfa_token:
                print("RoleArn=" + 'arn:aws:iam::' + ACCOUNT_NUMBER + r':role/' + IAM_ROLE)
                stsresponse = boto_sts.assume_role(
                    RoleArn='arn:aws:iam::' + ACCOUNT_NUMBER + r':role/' + IAM_ROLE,
                    RoleSessionName=str(uuid.uuid4()),
                    SerialNumber=serial_number,
                    TokenCode=mfa_token
                )
            else:
                print("RoleArn=" + 'arn:aws:iam::' + ACCOUNT_NUMBER + r':role/' + IAM_ROLE)
                stsresponse = boto_sts.assume_role(
                    RoleArn='arn:aws:iam::' + ACCOUNT_NUMBER + r':role/' + IAM_ROLE,
                    RoleSessionName=str(uuid.uuid4())
                )

            # Save the details from assumed role into vars
            newsession_id = stsresponse["Credentials"]["AccessKeyId"]
            newsession_key = stsresponse["Credentials"]["SecretAccessKey"]
            newsession_token = stsresponse["Credentials"]["SessionToken"]

            # Here I create a cloudformation client using the assumed creds.
            assumed_session = get_session(
                region,
                newsession_id,
                newsession_key,
                newsession_token
            )

        else:
            # Here I create a cloudformation client using environment creds.
            assumed_session = boto3.session.Session(region_name=region).client('cloudformation')

        cloudformation_assumed_client = assumed_session.client('cloudformation')
        response = cloudformation_assumed_client.describe_stacks(StackName=cloudformation_of_architecture)
        for key_value_pair in response["Stacks"][0]["Outputs"]:
            if key_value_pair["OutputKey"] == 'Cluster':
                cluster_name = key_value_pair["OutputValue"]
            if key_value_pair["OutputKey"] == 'ServiceName':
                service_name = key_value_pair["OutputValue"]

        ecs_assumed_client = assumed_session.client('ecs')

        response = ecs_assumed_client.list_tasks(cluster=cluster_name,desiredStatus='RUNNING',launchType='FARGATE')
        task_arns = response['taskArns']

        random_task_arn = random.choice(task_arns)

        random_task_id = random_task_arn.rsplit('/')[2]

        # SYNC DIRECTORIES USING AWSCLI
        print('Attempting to execute command interactively!')
        old_env = dict(os.environ)

        try:
            # SET NEW ENVRIONMENT
            env = os.environ.copy()
            env['LC_CTYPE'] = u'en_US.UTF'
            env['AWS_ACCESS_KEY_ID'] = newsession_id
            env['AWS_SECRET_ACCESS_KEY'] = newsession_key
            env['AWS_SESSION_TOKEN'] = newsession_token
            os.environ.update(env)

            run_list = ['ecs', 'execute-command', '--interactive', '--task', random_task_id, '--cluster', cluster_name]

            if container:
                run_list.append('--container')
                run_list.append(container)

            if command:
                run_list.append('--command')
                run_list.append(command)
            else:
                run_list.append('--command')
                run_list.append('/bin/sh')

            # RUN COMMAND
            exit_code = create_clidriver().main(run_list)
            if exit_code > 0:
                raise RuntimeError('AWS CLI exited with code {}'.format(exit_code))

            # OLD ENVIRONMENT COMES BACK
            os.environ.clear()
            os.environ.update(old_env)
        except subprocess.CalledProcessError as error:
            os.environ.clear()
            os.environ.update(old_env)
            traceback.print_tb(error.__traceback__)
            print(error.output)
            raise ValueError(str(error))
    except Exception as error:
        traceback.print_tb(error.__traceback__)
        raise ValueError(str(error))
    return
######################################################EXECUTE COMMAND LIBRARIES END HERE######################################################

######################################################CONFIGURE LIBRARIES START HERE######################################################
def configure(profile_name):

    print('Configuration command initiated!')

    print('')
    print("\033[4m" + 'IMPORTANT NOTICE STARTS HERE!' + "\033[0m")
    print('REMEMBER TO FILL OUT ALL OF THE FORMS USING THE COMMAND "aws configure" AS WELL OR THIS CLI WILL NOT PROPERLY FUNCTION!')
    print("\033[4m" + 'IMPORTANT NOTICE ENDS HERE!' + "\033[0m")
    print('')

    try:

        if os.path.exists(os.path.join(os.path.dirname(os.path.realpath(__file__)),profile_name)):
            with open(os.path.join(os.path.dirname(os.path.realpath(__file__)),profile_name),'r') as profile_file:
                data = json.loads(profile_file.read())
            profile_exists = True
        else:
            data = {}
            profile_exists = False

        if profile_exists:
            try:
                account_number = data['fluoride_cli_account_number']
            except:
                account_number = ''
            user_input = input('fluoride_cli_account_number['+account_number+']:').strip()
        else:
            user_input = input('fluoride_cli_account_number[]:').strip()
        if user_input:
            data['fluoride_cli_account_number']=str(user_input)
        if user_input == '**CLEAR**':
            data['fluoride_cli_account_number']=''

        if profile_exists:
            try:
                role_to_assume_to_target_account = data['fluoride_cli_role_to_assume_to_target_account']
            except:
                role_to_assume_to_target_account = ''
            user_input = input('fluoride_cli_role_to_assume_to_target_account['+role_to_assume_to_target_account+']:').strip()
        else:
            user_input = input('fluoride_cli_role_to_assume_to_target_account[]:').strip()
        if user_input:
            data['fluoride_cli_role_to_assume_to_target_account']=str(user_input)
        if user_input == '**CLEAR**':
            data['fluoride_cli_role_to_assume_to_target_account']=''

        if profile_exists:
            try:
                local_image_to_push = data['fluoride_cli_local_image_to_push']
            except:
                local_image_to_push = ''
            user_input = input('fluoride_cli_local_image_to_push['+local_image_to_push+']:').strip()
        else:
            user_input = input('fluoride_cli_local_image_to_push[]:').strip()
        if user_input:
            data['fluoride_cli_local_image_to_push']=str(user_input)
        if user_input == '**CLEAR**':
            data['fluoride_cli_local_image_to_push']=''

        if profile_exists:
            try:
                path_to_docker_folder = data['fluoride_cli_path_to_docker_folder']
            except:
                path_to_docker_folder = ''
            user_input = input('fluoride_cli_path_to_docker_folder['+path_to_docker_folder+']:').strip()
        else:
            user_input = input('fluoride_cli_path_to_docker_folder[]:').strip()
        if user_input:
            data['fluoride_cli_path_to_docker_folder']=str(user_input)
        if user_input == '**CLEAR**':
            data['fluoride_cli_path_to_docker_folder']=''

        if profile_exists:
            try:
                ecr_repo_to_push_to = data['fluoride_cli_ecr_repo_to_push_to']
            except:
                ecr_repo_to_push_to = ''
            user_input = input('fluoride_cli_ecr_repo_to_push_to['+ecr_repo_to_push_to+']:').strip()
        else:
            user_input = input('fluoride_cli_ecr_repo_to_push_to[]:').strip()
        if user_input:
            data['fluoride_cli_ecr_repo_to_push_to']=str(user_input)
        if user_input == '**CLEAR**':
            data['fluoride_cli_ecr_repo_to_push_to']=''

        if profile_exists:
            try:
                cloudformation_of_architecture = data['fluoride_cli_cloudformation_of_architecture']
            except:
                cloudformation_of_architecture = ''
            user_input = input('fluoride_cli_cloudformation_of_architecture['+cloudformation_of_architecture+']:').strip()
        else:
            user_input = input('fluoride_cli_cloudformation_of_architecture[]:').strip()
        if user_input:
            data['fluoride_cli_cloudformation_of_architecture']=str(user_input)
        if user_input == '**CLEAR**':
            data['fluoride_cli_cloudformation_of_architecture']=''

        if profile_exists:
            try:
                ecr_repo_to_make = data['fluoride_cli_ecr_repo_to_make']
            except:
                ecr_repo_to_make = ''
            user_input = input('fluoride_cli_ecr_repo_to_make['+ecr_repo_to_make+']:').strip()
        else:
            user_input = input('fluoride_cli_ecr_repo_to_make[]:').strip()
        if user_input:
            data['fluoride_cli_ecr_repo_to_make']=str(user_input)
        if user_input == '**CLEAR**':
            data['fluoride_cli_ecr_repo_to_make']=''

        if profile_exists:
            try:
                path_to_local_secrets = data['fluoride_cli_path_to_local_secrets']
            except:
                path_to_local_secrets = ''
            user_input = input('fluoride_cli_path_to_local_secrets['+path_to_local_secrets+']:').strip()
        else:
            user_input = input('fluoride_cli_path_to_local_secrets[]:').strip()
        if user_input:
            data['fluoride_cli_path_to_local_secrets']=str(user_input)
        if user_input == '**CLEAR**':
            data['fluoride_cli_path_to_local_secrets']=''

        if profile_exists:
            try:
                secret_store = data['fluoride_cli_secret_store']
            except:
                secret_store = ''
            user_input = input('fluoride_cli_secret_store['+secret_store+']:').strip()
        else:
            user_input = input('fluoride_cli_secret_store[]:').strip()
        if user_input:
            data['fluoride_cli_secret_store']=str(user_input)
        if user_input == '**CLEAR**':
            data['fluoride_cli_secret_store']=''

        with open(os.path.join(os.path.dirname(os.path.realpath(__file__)),profile_name), "w+") as outfile:
            json.dump(data, outfile)

    except Exception as error:
        traceback.print_tb(error.__traceback__)
        print('Configuration command failed!')
        raise ValueError(str(error))
    print('Configuration command was successful!')
    return
######################################################CONFIGURE LIBRARIES STOP HERE######################################################

######################################################CHECK PROFILE LIBRARIES START HERE######################################################
def check_profile():
    try:
        if os.path.exists(os.path.join(os.path.dirname(os.path.realpath(__file__)),'current_fluoride_profile_config.txt')):
            with open(os.path.join(os.path.dirname(os.path.realpath(__file__)),'current_fluoride_profile_config.txt'),'r') as config_file:
                current_profile = config_file.read().strip()
            default_profile_exists = True
        else:
            default_profile_exists = False

        if default_profile_exists:
            print('DEFAULT PROFILE IS SET')
            print('######PROFILE LIST START########')
            for file in os.listdir(os.path.join(os.path.dirname(os.path.realpath(__file__)))):
                if file not in ['lib.py', 'cli.py' ,'.DS_Store','__init__.py','__pycache__','fluoride','temp_store','current_fluoride_profile_config.txt']:
                    if file == current_profile:
                        print("\033[4m"+current_profile+"\033[0m")
                    else:
                        print(file)
            print('######PROFILE LIST END########')
            print('CURRENT PROFILE ATTRIBUTES:')
            with open(os.path.join(os.path.dirname(os.path.realpath(__file__)), current_profile), 'r') as profile_file:
                data = json.loads(profile_file.read())
            print(data)


        else:
            print('DEFAULT PROFILE IS NOT SET')
            print('######PROFILE LIST START########')

            for file in os.listdir(os.path.join(os.path.dirname(os.path.realpath(__file__)))):
                if file not in ['lib.py', 'cli.py' ,'.DS_Store','__init__.py','__pycache__','fluoride','temp_store','current_fluoride_profile_config.txt']:
                    print(file)

            print('######PROFILE LIST END########')


    except Exception as error:
        traceback.print_tb(error.__traceback__)
        raise ValueError(str(error))
    return
######################################################CONFIGURE LIBRARIES STOP HERE######################################################

######################################################SET PROFILE LIBRARIES START HERE######################################################
def set_profile(profile_name):
    try:
        profile_not_found = True
        for file in os.listdir(os.path.join(os.path.dirname(os.path.realpath(__file__)))):
            if file not in ['lib.py', 'cli.py' ,'.DS_Store','__init__.py','__pycache__','fluoride','temp_store','current_fluoride_profile_config.txt']:
                if file == profile_name:
                    profile_not_found = False

        if profile_not_found:
            print('Profile named '+profile_name+' was not detected as an existing profile.')
            print('Here is a list of profiles we have detected:')
            print('######PROFILE LIST START########')

            for file in os.listdir(os.path.join(os.path.dirname(os.path.realpath(__file__)))):
                if file not in ['lib.py', 'cli.py' ,'.DS_Store','__init__.py','__pycache__','fluoride','temp_store','current_fluoride_profile_config.txt']:
                    print(file)

            print('######PROFILE LIST END########')
            return

        with open(os.path.join(os.path.dirname(os.path.realpath(__file__)),'current_fluoride_profile_config.txt'),'w+') as config_file:
            config_file.write(profile_name)

    except Exception as error:
        traceback.print_tb(error.__traceback__)
        raise ValueError(str(error))
    return
######################################################SET LIBRARIES STOP HERE######################################################

######################################################SET PROFILE LIBRARIES START HERE######################################################
def delete_profile(profile_name):
    try:
        profile_not_found = True
        for file in os.listdir(os.path.join(os.path.dirname(os.path.realpath(__file__)))):
            if file not in ['lib.py', 'cli.py' ,'.DS_Store','__init__.py','__pycache__','fluoride','temp_store','current_fluoride_profile_config.txt']:
                if file == profile_name:
                    profile_not_found = False

        if profile_not_found:
            print('Profile named '+profile_name+' was not detected as an existing profile.')
            print('Here is a list of profiles we have detected:')
            print('######PROFILE LIST START########')

            for file in os.listdir(os.path.join(os.path.dirname(os.path.realpath(__file__)))):
                if file not in ['lib.py', 'cli.py' ,'.DS_Store','__init__.py','__pycache__','fluoride','temp_store','current_fluoride_profile_config.txt']:
                    print(file)

            print('######PROFILE LIST END########')
            return

        os.remove(os.path.join(os.path.join(os.path.dirname(os.path.realpath(__file__))),profile_name))
        if os.path.exists(os.path.join(os.path.dirname(os.path.realpath(__file__)), 'current_fluoride_profile_config.txt')):
            with open(os.path.join(os.path.dirname(os.path.realpath(__file__)), 'current_fluoride_profile_config.txt'),'r') as config_file:
                current_profile = config_file.read().strip()
            if current_profile == profile_name:
                clear_profile_config()

    except Exception as error:
        traceback.print_tb(error.__traceback__)
        raise ValueError(str(error))
    return
######################################################SET LIBRARIES STOP HERE######################################################

######################################################CLEAR PROFILE CONFIG LIBRARIES START HERE######################################################
def clear_profile_config():
    try:
        os.remove(os.path.join(os.path.dirname(os.path.realpath(__file__)),'current_fluoride_profile_config.txt'))
    except Exception as error:
        traceback.print_tb(error.__traceback__)
        raise ValueError(str(error))
    return
######################################################CLEAR PROFILE CONFIG LIBRARIES STOP HERE######################################################

######################################################WHERE AM I LIBRARIES START HERE######################################################
def where_am_i(directory_path):
    try:
        print('Here is the directory where your config files are located:')
        print(directory_path)
        print('You can drag profile files out of this directory to another directory specified by where_am_i on another machine to import profiles to another location.')
        print('Putting profiles in the path specified by this command will import them into your cli.')
    except Exception as error:
        traceback.print_tb(error.__traceback__)
        raise ValueError(str(error))
    return
######################################################WHERE AM I LIBRARIES STOP HERE######################################################


