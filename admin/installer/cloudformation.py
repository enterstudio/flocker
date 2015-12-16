# Converted from EC2InstanceSample.template located at:
# http://aws.amazon.com/cloudformation/aws-cloudformation-templates/
import os

from troposphere import FindInMap, GetAtt, Base64, Join
from troposphere import Parameter, Output, Ref, Template, GetAZs, Select
from troposphere.s3 import Bucket
import troposphere.ec2 as ec2

OWNER = u"richardw"
NUM_NODES = 2
NODE_NAME_TEMPLATE = u"{owner}flockerdemo{index}"
S3_SETUP = 'setup_s3.sh'
FLOCKER_CONFIGURATION_GENERATOR = 'flocker-configuration-generator.sh'
FLOCKER_CONFIGURATION_GETTER = 'flocker-configuration-getter.sh'


def sibling_lines(filename):
    dirname = os.path.dirname(__file__)
    path = os.path.join(dirname, filename)
    with open(path, 'r') as f:
        return f.readlines()

template = Template()

keyname_param = template.add_parameter(Parameter(
    "KeyName",
    Description="Name of an existing EC2 KeyPair to enable SSH "
                "access to the instance",
    Type="String",
))


access_key_id_param = template.add_parameter(Parameter(
    "AccessKeyID",
    Description="Your Amazon AWS access key ID",
    Type="String",
))

secret_access_key_param = template.add_parameter(Parameter(
    "SecretAccessKey",
    Description="Your Amazon AWS secret access key.",
    Type="String",
))

template.add_mapping('RegionMap', {
    # richardw-test1 AMI generated from a running acceptance test node.
    "us-east-1":      {"AMI": "ami-6cabe306"},
})

instances = []
zone = Select(0, GetAZs(""))

s3bucket = Bucket('FlockerConfig',
                  DeletionPolicy='Delete')
template.add_resource(s3bucket)

for i in range(NUM_NODES):
    node_name = NODE_NAME_TEMPLATE.format(owner=OWNER, index=i)
    ec2_instance = ec2.Instance(
        node_name,
        ImageId=FindInMap("RegionMap", Ref("AWS::Region"), "AMI"),
        InstanceType="m3.large",
        KeyName=Ref(keyname_param),
        # TODO: create and use unique SecurityGroup for this install.
        SecurityGroups=["acceptance"],
        AvailabilityZone=zone,
    )
    user_data = [
        '#!/bin/bash\n',
        'aws_region="', Ref("AWS::Region"), '"\n',
        'aws_zone="', zone, '"\n',
        'access_key_id="', Ref(access_key_id_param), '"\n',
        'secret_access_key="', Ref(secret_access_key_param), '"\n',
        's3_bucket="', Ref(s3bucket), '"\n',
        'node_count="{}"\n'.format(NUM_NODES),
        'node_number="{}"\n'.format(i),
    ]
    user_data += sibling_lines(S3_SETUP)

    if i == 0:
        control_service_instance = ec2_instance
        user_data += sibling_lines(FLOCKER_CONFIGURATION_GENERATOR)
    else:
        ec2_instance.DependsOn = control_service_instance.name

    user_data += sibling_lines(FLOCKER_CONFIGURATION_GETTER)
    ec2_instance.UserData = Base64(Join("", user_data))

    template.add_resource(ec2_instance)
    template.add_output([
        Output(
            "{}PublicIP".format(node_name),
            Description="Public IP address of the newly created EC2 instance",
            Value=GetAtt(ec2_instance, "PublicIp"),
        ),
        Output(
            "{}PublicDNS".format(node_name),
            Description="Public DNSName of the newly created EC2 instance",
            Value=GetAtt(ec2_instance, "PublicDnsName"),
        ),
    ])

template.add_output([
    Output(
        "AvailabilityZone",
        Description="Availability Zone of the newly created EC2 instance",
        Value=zone,
    ),
])
template.add_output(Output(
    "ClusterCert",
    Description="Flocker cluster cert",
    Value=Join("", ["ssh -i ", Ref(keyname_param), ".pem ubuntu@",
               GetAtt(control_service_instance, "PublicDnsName"),
               " sudo cat /etc/flocker/cluster.crt"])
    )
)
template.add_output(Output(
    "BucketName",
    Value=Ref(s3bucket),
    Description="Name of S3 bucket to hold Flocker certs"
))

print(template.to_json())