import os 
import yaml

import inspect
from datetime import datetime, timedelta

from flask import Flask, g , session, render_template
from flask import request, redirect, url_for
 
import urllib, json
from celery import Celery
from celery.bin import worker

#from flask.ext.celery import Celery

# ldap authentication
from flask_simpleldap import LDAP, LDAPException


app = Flask(__name__)


y = yaml.load( open( 'configuration.yaml' , 'r' ) , Loader=yaml.FullLoader )


app.config['APP_FOLDER']				= os.path.abspath( ''.join(y['Directories']['app_folder']) )				# app folder
app.config['UPLOADED_FILES_DEST'] 		= os.path.abspath( ''.join(y['Directories']['artifacts_upload']) )		# uploaded artifacts files
app.config['UPLOADED_FILES_DEST_RAW'] 	= os.path.abspath( ''.join(y['Directories']['artifacts_upload_raw']) )	# uploaded artifacts raw files
app.config['PARSER_PATH'] 				= os.path.abspath( ''.join(y['Directories']['app_parsers']) )			# parser folder
app.config['CELERY_BROKER_URL'] 	    = y['CELERY']['CELERY_BROKER_URL']
app.config['CELERY_RESULT_BACKEND']     = y['CELERY']['CELERY_RESULT_BACKEND']
app.config['CELERY_TASK_ACKS_LATE']     = y['CELERY']['CELERY_TASK_ACKS_LATE']
app.config['CELERY_IGNORE_RESULT']      = False
app.config['celery_task_name']          = y['CELERY']['celery_task_name']

celery_app = Celery(app , backend =app.config['CELERY_RESULT_BACKEND'] , broker  =app.config['CELERY_BROKER_URL'])

celery_app.conf.worker_max_tasks_per_child=1 # terminate celery worker when done and re-initilize other one to free memory

# the worker name format is "<node>@<worker-name>", if the node not specified it will use "celery@<worker-name>"
if "@" not in y['CELERY']['CELERY_WORKER_NAME']:
    y['CELERY']['CELERY_WORKER_NAME'] = "celery@" + y['CELERY']['CELERY_WORKER_NAME']


app.secret_key = y['Kuiper']['secret_key']


app.config['DB_NAME']                   = y['MongoDB']['DB_NAME']
app.config['DB_IP']                   	= y['MongoDB']['DB_IP']
app.config['DB_PORT']                   = y['MongoDB']['DB_PORT']

app.config['SIDEBAR_OPEN']              = y['adminlte']['SIDEBAR_OPEN']



app.config['LDAP_HOST']                 = y['LDAP_auth']['LDAP_HOST']
app.config['LDAP_PORT']                 = y['LDAP_auth']['LDAP_PORT'] 
app.config['LDAP_SCHEMA']               = y['LDAP_auth']['LDAP_SCHEMA']
app.config['LDAP_USE_SSL']              = y['LDAP_auth']['LDAP_USE_SSL']  
app.config['LDAP_BASE_DN']              = y['LDAP_auth']['LDAP_BASE_DN']
app.config['LDAP_USERNAME']             = y['LDAP_auth']['LDAP_USERNAME']
app.config['LDAP_PASSWORD']             = y['LDAP_auth']['LDAP_PASSWORD']

app.config['LDAP_USER_OBJECT_FILTER']   = y['LDAP_auth']['LDAP_USER_OBJECT_FILTER']

if y['LDAP_auth']['enabled']:
    ldap = LDAP(app) 

# ===================== Logger - START ===================== # 
# class Logger to handle all Kuiper logs
class Logger:
    ERROR     = 0
    WARNING   = 1
    INFO      = 2
    DEBUG     = 3
    

    def __init__(self , log_file , level=None):
        self.log_file   = log_file
        self.level      = level if level is not None else self.ERROR
        self.level_names = {
            0 : 'ERROR',
            1 : 'WARNING',
            2 : 'INFO',
            3 : 'DEBUG'
        }

        

        self.logfile_handle = open(log_file , 'a')

        # if the file not empty write the log header
        if not os.stat(log_file).st_size:
            self.logfile_handle.write('"Timestamp","LogLevel","Reference","Category","Message","Reaspm"\n')

    def logger(self, level , type , message , reason=""):
        if self.level < level:
            return
        ins = inspect.stack()[1]
        caller_function = ins[3]
        caller_line     = ins[2] #inspect.getframeinfo(ins[0].lineno)
        caller_file     = os.path.basename(ins[1])
        msg = '"%s","[%s]","%s","%s","%s","%s"' % (datetime.now() , self.level_names[level] , caller_file + "." + caller_function + "[Lin."+str(caller_line)+"]" , type, message , reason)
        print msg
        self.logfile_handle.write(msg + "\n")
        self.logfile_handle.flush()


if y['Kuiper']['logs_level'] == 'DEBUG':
    log_level = Logger.DEBUG
elif y['Kuiper']['logs_level'] == 'INFO':
    log_level = Logger.INFO
elif y['Kuiper']['logs_level'] == 'WARNING':
    log_level = Logger.WARNING
else:
    log_level = Logger.ERROR
    
logger = Logger(os.path.join(y['Logs']['log_folder'] , y['Logs']['kuiper_log']) , log_level )

# ===================== Logger - END ===================== # 

#from app import producer
#import multiprocessing
#from billiard.context import Process
import billiard as billiard

from controllers import case_management,admin_management,API_management


# redirector to the actual home page 
@app.route('/')
def home():
    return redirect(url_for('home_page'))


# ================= ldap authentication 

def is_authenticated():
    return 'last_visit' in session and 'user_id' in session

@app.before_request
def before_request():
    #print("IM HERE0")
    #get_kafka_data_print_test("rcra-report-topic")
    #print("IM HERE1")
    #t1 = billiard.Process(target=get_kafka_data_print_test, args=("rcra-report-topic",))
    #t2 = Process(target=get_kafka_data_print_test, args=("dtm-alert",))
    # t1.start()

    g.user = None
    if y['LDAP_auth']['enabled'] == False or request.full_path.startswith('/static') or request.full_path.startswith('/login') or request.full_path.startswith('/logout'):
        return
    
    # check if the api token correct
    if request.full_path.startswith('/api'):
        request_str =  urllib.unquote(request.data).decode('utf8')
        request_json = json.loads(request_str)['data']

        if request_json['api_token'] == y['Kuiper']['api_token']:
            return
    
    if is_authenticated():
        session_expired = datetime.now() > session['last_visit'] + timedelta(minutes = 30)
        if 'last_visit' not in session or session_expired:
            return redirect(url_for('login', message="Session expired!", url=request.full_path))

        session['last_visit'] = datetime.now()
        return 
    

    return redirect(url_for('login', message=None))
    



@app.route('/login', methods=['GET', 'POST'])
def login():
    if y['LDAP_auth']['enabled'] == False:
        return redirect(url_for('home'))

    message = request.args.get('message' , None)
    if is_authenticated() and message != "Session expired!":
        return redirect(url_for('home'))
    if request.method == 'POST':
        user = request.form['user']
        passwd = request.form['passwd']
        try:
            test = ldap.bind_user(user, passwd)
        except LDAPException as e :
            message = str(e)
            return render_template('login.html' , msg=message )

        if test is None or passwd == '':
            return render_template('login.html' , msg='Invalid credentials')
        else:
            session['user_id'] = request.form['user']
            session['last_visit'] = datetime.now()

            url = request.args.get('url' , None)
            if url is None:
                return redirect(url_for('home'))
            else:
                return redirect(url)

    message = request.args.get('message' , None)
    return render_template('login.html' , msg=message )

@app.route('/logout', methods=['GET'])
def logout():

    if y['LDAP_auth']['enabled'] == False:
        return redirect(url_for('home'))
        
        
    try:
        del session['user_id']
        del session['last_visit']
    except: 
        pass
    
    message = request.args.get('message' , None)
    url     = request.args.get('url' , None)
    if message is not None and url is not None:
        return redirect(url_for('login', message=message, url=request.full_path)) 
    return redirect(url_for('login')) 
