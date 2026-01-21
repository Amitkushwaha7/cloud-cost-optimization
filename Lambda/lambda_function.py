import boto3
import datetime
import os
import pytz

ec2 = boto3.client('ec2')
cloudwatch = boto3.client('cloudwatch')
sns = boto3.client('sns')
ddb = boto3.resource('dynamodb')

TABLE_NAME = os.environ['TABLE_NAME']
SNS_TOPIC_ARN = os.environ['SNS_TOPIC_ARN']   
DRY_RUN = os.environ['DRY_RUN'].lower() == "true"
CPU_THRESHOLD = int(os.environ['CPU_THRESHOLD'])
TIMEZONE = os.environ['TIMEZONE']

table = ddb.Table(TABLE_NAME)

def get_cpu_utilization(instance_id):
    response = cloudwatch.get_metric_statistics(
        Namespace='AWS/EC2',
        MetricName='CPUUtilization',
        Dimensions=[{'Name': 'InstanceId', 'Value': instance_id}],
        StartTime=datetime.datetime.utcnow() - datetime.timedelta(minutes=30),
        EndTime=datetime.datetime.utcnow(),
        Period=300,
        Statistics=['Average']
    )

    if not response['Datapoints']:
        return None

    latest = sorted(response['Datapoints'], key=lambda x: x['Timestamp'])[-1]
    return latest['Average']

def lambda_handler(event, context):
    tz = pytz.timezone(TIMEZONE)
    now = datetime.datetime.now(tz)
    hour = now.hour

    instances = ec2.describe_instances(Filters=[
        {'Name': 'tag:AutoStop', 'Values': ['Yes']},
        {'Name': 'tag:Environment', 'Values': ['Dev', 'Test']},
        {'Name': 'tag:Critical', 'Values': ['No']},
        {'Name': 'instance-state-name', 'Values': ['running']}
    ])

    for res in instances['Reservations']:
        for inst in res['Instances']:
            instance_id = inst['InstanceId']
            cpu = get_cpu_utilization(instance_id)

            reason = None
            if hour >= 20 or hour < 8:
                reason = "After hours"
            elif cpu is not None and cpu < CPU_THRESHOLD:
                reason = f"Low CPU: {cpu}%"

            if reason:
                if not DRY_RUN:
                    ec2.stop_instances(InstanceIds=[instance_id])

                table.put_item(Item={
                    "InstanceId": instance_id,
                    "Timestamp": str(now),
                    "Reason": reason
                })

                sns.publish(
                    TopicArn=SNS_TOPIC_ARN,
                    Subject="EC2 Optimization Alert",
                    Message=f"Stopped {instance_id} due to {reason}"
                )

    return {"statusCode": 200, "body": "Optimization complete"}
