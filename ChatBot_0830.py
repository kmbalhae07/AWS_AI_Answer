from flask import Flask, request, render_template_string, redirect, url_for,flash,jsonify
from flask_cors import CORS
from konlpy.tag import Komoran
from botocore.exceptions import NoCredentialsError
from flask_socketio import SocketIO, emit
import json
import openai
import re
from flask import render_template
from datetime import datetime
import urllib
import pytz
import boto3
import ssl #Test Key
import threading
import time
import re
from jin import jin_time, emergency

# AWS 자격 증명 설정
aws_access_key_id = '***************'
aws_secret_access_key = '***************'
aws_region = 'ap-northeast-2'

# DynamoDB 클라이언트 생성
dynamodb = boto3.client('dynamodb', region_name=aws_region,
                        aws_access_key_id=aws_access_key_id,
                        aws_secret_access_key=aws_secret_access_key)
                        
# DynamoDB 테이블 이름
table_name = 'test_2_chatbot'  # DynamoDB 테이블 이름으로 변경
table_name1 = 'Chatbot_All_Ace'
app = Flask(__name__)
app.secret_key = 'team2'
CORS(app)
# AWS 서비스 객체 생성
s3 = boto3.client('s3')

openai.api_key = '**************************'  # API

# 대화 상태 저장용 dictionary
conversations = {}

def generate_response(prompt):
    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": prompt}
        ]
    )
    return response['choices'][0]['message']['content'].strip()

@app.route('/chat', methods=['POST'])
def chat():
    with app.app_context():
        data = request.json
        user_id = data.get('user_id')
        user_message = data.get('message')
        print(user_id)
        print(user_message)
        if not user_id or not user_message:
            return {"error": "사용자 아이디나 메세지가 누락됨"}, 200
    
        # 대화 상태 초기화
        if user_id not in conversations or user_message == '안녕하세요':
            conversations[user_id] = {
                'step': -1,
                'name': '',
                'incident': '',
                'incident_status': '',
                'location': '',
                'reporttime':'',
                'report_emergency':'', #사용자 긴급도
                'timestamp': '',
                'emergency':'',
            }
            return {"message": "안녕하세요. 중대재해 관리 챗봇입니다. 성함을 알려주세요."}, 200
            
        conversation = conversations[user_id]

        # 어떤 단계여도 말을 안하거나 '악'또는 '윽'이 들어갈때 긴급으로 표기. 
        emergen,time=emergency(user_message)
        if emergen=='긴급':
            conversation['name']=str(user_id) # 긴급은 requset의 user_id를 따옴.
            conversation['timestamp'] = time 
            conversation['emergency']='긴급'
            # DynamoDB에 데이터 저장
            response = dynamodb.put_item(
                TableName=table_name,
                Item={
                    'user_id': {'S': conversation['emergency']},
                    'incident': {'S': conversation['incident']},
                    'location': {'S': conversation['location']},
                    'reporttime' : {'S' : conversation['reporttime']}, #실시간 시각
                    'report_emergency':{'S': conversation['report_emergency']},
                    'timestamp': {'S': str(conversation['timestamp'])},
                    'incident_status': {'S': conversation['incident_status']}
               }
            )
            response1 = dynamodb.put_item(
                    TableName=table_name1,
                    Item={
                        'emergency': {'S': conversation['emergency']},
                        'incident': {'S': conversation['incident']},
                        'location': {'S': conversation['location']},
                        'reporttime' : {'S' : conversation['reporttime']},
                        'timestamp': {'S': str(conversation['timestamp'])}, #실시간 시각
                        'user_id' : {'S' : conversation['name']},
                        'report_emergency':{'S': conversation['report_emergency']},
                        'incident_status': {'S': conversation['incident_status']},
                        'minutes' : {'S':''}

               }
            )
            conversation['step']=6

        # 대화 상태에 따른 처리
        if conversation['step'] == -1:
            conversation['name'] = user_message
            conversation['step'] += 1
            return {"message": f"{conversation['name']}님, 재해 상황을 알려주시겠어요? Ex) 화재 발생, 누전 감지, 사람이 다침 등)"}, 200
        
        elif conversation['step'] == 0:
            prompt = f"'{user_message}'라는 문장에서 잠재적인 위험 상황으로 판단되는 구절이 있다면, 해당 구절만 답해. 다른 설명, 말 필요없으니까 뒤에 붙이지 마. 참고로 '불이 난다', '건물에 금이 간다','불이야', '기둥에 금이간다'와 같은 상황은 잠재적 위험 상황으로 판단해야해. 잠재적인 위험 상황을 설명하는 구절이 없다면 0이라고 말해."
            conversation['incident'] = generate_response(prompt)
                
            if user_message == "불이야":
                conversation['incident'] == user_message
                conversation['step'] += 1
                print(conversation['incident'])
                return {"message": f"[사건 : {conversation['incident']}]. \n 진행사항이 어떻게 되나요?"}, 200
            elif '0' in conversation['incident']:
                return {"message": "재해 상황이 아닌 것으로 판단됩니다. 다시 말씀해주세요."}, 200  
            else:
                conversation['step'] += 1
                return {"message": f"[사건 : {conversation['incident']}]. \n 진행사항이 어떻게 되나요?"}, 200
        
        elif conversation['step'] ==1:
            conversation['incident_status'] = user_message  # 진행 상황 저장 -------------------------------------------------수정사항
            conversation['step']+=1
            return {"message": "곧 사고가 일어날 것 같다면 '네'를, 당장 사고가 일어나진 않지만 예방조치가 필요하다면 '아니요'를 말씀해주세요."}
            
        elif conversation['step'] == 2:
            conversation['report_emergency']=user_message
            conversation['step'] += 1
            return {"message": "위치를 자세히 설명해 주세요."}, 200
    
        elif conversation['step'] == 3:
            prompt = f"'{user_message}'라는 문장에서 장소를 의미하는 구절이나 특정한 사물이 있다면, 해당 구절만 다말해. 다른 설명, 말 필요없으니까 추가적인 말을 덧붙이지 마. 없으면 0만 말해."
            conversation['location'] = generate_response(prompt)
            if '0' not in conversation['location']:
                conversation['step'] += 1
                return {"message": f"[발생 장소 : {conversation['location']}].\n 발견 시간을 알려주세요. (Ex. 오전 12시 30분, 5분 전)"}, 200  
            else:
                return {"message": "죄송합니다. 다시 말씀해 주시겠어요?"}, 200
                
        elif conversation['step'] == 4: #시간을 나타내는 글자만 숫자로 바꾸기 # DB에는 현재 날짜랑 시각을 저장해야 한다.
            # 현재 시간 가져오기
            korea_timezone = pytz.timezone('Asia/Seoul') 
            current_time = datetime.now(korea_timezone)
            report_time = current_time.strftime('%Y-%m-%d %H:%M:%S') # 원하는 포맷으로 시간 포맷팅
            
            # DB에 저장
            conversation['timestamp'] = report_time  

            # chatgpt
            User_Message=user_message
            hour, minute, word= jin_time(User_Message, report_time) # jin.py의 jin_time으로 모듈화 시킴. 
            if 0 <= hour < 24 and 0 <= minute < 60:
                conversation['reporttime'] = f"{hour}시{minute}분 {word}" 
                conversation['step'] += 1
                report = f"[{conversation['name']}님, 신고하신 상황은 {conversation['incident']}이며 {conversation['location']}에서 발생되었고 {conversation['reporttime']}에 발견되었습니다.] \n 해당 사건의 상황은 {conversation['incident_status']}입니다."
                return {"message":  report + "\n"+"위의 정보가 모두 정확하신가요? (네 혹은 아니오로 답변해주세요.)"}, 200
            else:
                return {"message": "죄송합니다. 시간 형식이 잘못되었습니다. 'HH시' 혹은 'HH시 MM분' 형태로 다시 입력해 주세요."}, 200 
    
        elif conversation['step'] == 5:
            if '네' in user_message or '맞아' in user_message:
                print(conversation)
                question = f"이번에 발생한 사건은 {conversation['incident']}로, {conversation['reporttime']}에 {conversation['location']}에서 발생했습니다. 그리고 해당 사건의 상황은 '{conversation['incident_status']}'입니다. 이 사건이 긴급하다고 판단되면 긴급, 아니라면 경고로만 답해 주세요. 다른 말 쓰지 마세요."
                gpt_response = generate_response(question)
                conversation['emergency']=gpt_response
                # DynamoDB에 데이터 저장
                response = dynamodb.put_item(
                    TableName=table_name,
                    Item={
                        'user_id': {'S': conversation['emergency']},
                        'incident': {'S': conversation['incident']},
                        'location': {'S': conversation['location']},
                        'reporttime' : {'S' : conversation['reporttime']},
                        'timestamp': {'S': str(conversation['timestamp'])}, #실시간 시각
                        'report_emergency':{'S': conversation['report_emergency']},
                        'incident_status': {'S': conversation['incident_status']}
                    }
                    )
                response1 = dynamodb.put_item(
                    TableName=table_name1,
                    Item={
                        'emergency': {'S': conversation['emergency']},
                        'incident': {'S': conversation['incident']},
                        'location': {'S': conversation['location']},
                        'reporttime' : {'S' : conversation['reporttime']},
                        'timestamp': {'S': str(conversation['timestamp'])}, #실시간 시각
                        'user_id' : {'S' : conversation['name']},
                        'report_emergency':{'S': conversation['report_emergency']},
                        'incident_status': {'S': conversation['incident_status']},
                        'minutes' : {'S':''}
                    }
                )
                print(response)
                return {"message": "네, 감사합니다. 중간관리자에게 "+ gpt_response + "로 보고되었습니다." }, 200
                # 중간관리자에게 연락을 ���할 때 신고시간이 접수된 시간까지  추가할 수 있도록 하기
    
            elif '아니오' in user_message:
                conversation['step'] = -1  # 대화를 초기 상태로 리셋
                return {"message": "알겠습니다. 정보를 다시 입력해주세요. \n 성함을 다시 알려주세요."}, 200
            else:
                return {"message": "죄송합니다. '네' 혹은 '아니오'로 답변해주세요."}, 200
                
        elif conversation['step'] == 6:
            return {"message": "네, 감사합니다. 중간관리자에게 긴급으로 보고되었습니다." }, 200

        else:
            return {"error": "Unexpected state"}, 400


# 아이디와 비밀번호 (임시로 hard-coded)
VALID_USERNAME = "admin"
VALID_PASSWORD = "1234"

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if username == VALID_USERNAME and password == VALID_PASSWORD:
            flash("로그인에 성공하였습니다.")
            return render_template('manager1.html')
        else:
            error = "아이디 혹은 비밀번호가 맞지 않습니다."
    return render_template('login.html', error=error)

#임시 코드
@app.route('/manager1',  methods=['POST'])
def manager1():
    #반환된 값 dynamoDB에 저장
    data = request.json
    minutes = data.get('minutes')
    user_id = data.get('user_id')
    timestamp=data.get('timestamp')

    if minutes is not None and user_id is not None and timestamp is not None:
        # DynamoDB에 데이터 삽입
        update_expression = "SET minutes = :val"  # 업데이트할 필드와 값을 설정
        expression_values = {":val": {'S': str(minutes)}}  # 'N' 타입으로 설정
        
    
        response1 = dynamodb.update_item(
            TableName=table_name1,
            Key={"emergency": {"S": user_id}, 'timestamp': {'S': timestamp}},
            UpdateExpression=update_expression,
            ExpressionAttributeValues=expression_values
        )
    return render_template('manager1.html')
        
@app.route('/')
def home():
    return render_template('select.html')

@app.route('/user')
def user():
    return render_template('user.html')

@app.route('/upload', methods=['POST'])
def upload_audio():
    with app.app_context():  # 애플리케이션 컨텍스트 설정
        if 'audio' not in request.files:
            return jsonify({'error': '음성 파일이 제공되지 않았습니다.'}), 400

        audio_file = request.files['audio']
        if audio_file.filename == '':
            return jsonify({'error': '선택된 파일이 없습니다.'}), 400

        try:
            # 음성 파일을 Amazon S3에 업로드
            s3 = boto3.client('s3', aws_access_key_id=aws_access_key_id,
                            aws_secret_access_key=aws_secret_access_key, region_name=aws_region)
            s3_key = f'testVoiceFile/{datetime.now().strftime("%Y-%m-%d_%H-%M-%S")}.wav'
            s3.upload_fileobj(audio_file, 'team2tests3', s3_key)
            
            # Transcribe 작업 시작
            audio_s3_uri = f's3://team2tests3/{s3_key}'
            transcribe_job_name = f'transcribe-{datetime.now().strftime("%Y%m%d%H%M%S")}'        
            transcribe = boto3.client('transcribe', aws_access_key_id=aws_access_key_id,
                                      aws_secret_access_key=aws_secret_access_key, region_name=aws_region)
    
            transcribe.start_transcription_job (
                TranscriptionJobName=transcribe_job_name,
                Media={'MediaFileUri': audio_s3_uri},
                MediaFormat='webm',
                LanguageCode='ko-KR'
            )

            STT = wait_for_transcribe_completion(transcribe, transcribe_job_name, audio_s3_uri)
            return STT
            
        except NoCredentialsError:
            print("AWS자격 증명 오류")
            return jsonify({'error': 'Amazon AWS 자격 증명을 찾을 수 없습니다.'}), 500
        except Exception as e:
            print(" 음성 처리 인식 오류")
            return jsonify({'error': '음성 처리 오류', 'details': str(e)}), 500
        
def load_transcribed_text_from_uri(uri):
    response = urllib.request.urlopen(uri)
    data = json.loads(response.read())
    transcribed_text = data['results']['transcripts'][0]['transcript']
    return transcribed_text
    
 # Transcribe 작업이 끝나면 결과값을 불러옴
def wait_for_transcribe_completion(transcribe_client, job_name, transcribed_text_uri):
    with app.app_context():
        while True:
            response = transcribe_client.get_transcription_job(TranscriptionJobName=job_name)
            job_status = response['TranscriptionJob']['TranscriptionJobStatus']
    
            if job_status == 'COMPLETED':
                if 'TranscriptFileUri' in response['TranscriptionJob']['Transcript']:
                    transcribed_text_uri = response['TranscriptionJob']['Transcript']['TranscriptFileUri']
                    transcribed_text = load_transcribed_text_from_uri(transcribed_text_uri)
                    return jsonify({'message': '음성 처리 및 텍스트 변환 완료', 'transcribed_text': transcribed_text}), 200
                    break
            elif job_status == 'FAILED':
                print('Transcribe 작업이 실패함')
                break
            else:
                time.sleep(10)

    
if __name__ == '__main__':
    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS) #Test SSL
    ssl_context.load_cert_chain(certfile='server.crt', keyfile='server.key', password='') #Test SSL
    app.run(host='0.0.0.0', port=8443, ssl_context=ssl_context, debug=True) #Test SSL