# MarketMate EC2 Deployment

This folder contains a CloudFormation template for a minimal EC2 demo deployment.

## Cost Guardrails

This template is designed to be free-tier eligible, not guaranteed free:

- EC2 instance type defaults to `t3.micro`.
- T-family CPU credits are set to `standard` to avoid unlimited-mode surplus CPU charges.
- Root EBS volume defaults to 8 GB `gp3`.
- No Elastic IP is created.
- The instance uses Amazon Linux 2023 via AWS's public SSM AMI parameter.
- SSH is not opened; use AWS Systems Manager Session Manager if you need shell access.
- The app port defaults to `5273`.
- The Splunk Distribution of OpenTelemetry Collector is installed using Splunk's Linux installer script.
- The app exports OTLP traces to the local collector at `http://127.0.0.1:4318/v1/traces`.
- The app and collector set `deployment.environment=marketmate` by default.
- Splunk and OpenAI secrets are read from encrypted SSM SecureString parameters at boot.

Before creating the stack, confirm your EC2 Free Tier eligibility in AWS Billing/EC2. AWS’s current docs say Free Tier details differ based on whether the account was created before or after July 15, 2025. AWS also charges public IPv4 addresses, though EC2 Free Tier includes 750 public IPv4 hours/month for eligible accounts during the Free Tier period.

## Deploy

Replace the VPC/subnet/repo values:

```bash
aws cloudformation create-stack \
  --stack-name marketmate-python-demo \
  --template-body file://infra/marketmate-ec2-free-tier.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameters \
    ParameterKey=GitRepoUrl,ParameterValue=https://github.com/YOUR_USER/YOUR_REPO.git \
    ParameterKey=GitBranch,ParameterValue=main \
    ParameterKey=VpcId,ParameterValue=vpc-xxxxxxxx \
    ParameterKey=SubnetId,ParameterValue=subnet-xxxxxxxx \
    ParameterKey=AppIngressCidr,ParameterValue=YOUR_IP/32 \
    ParameterKey=SplunkAccessTokenParameterName,ParameterValue=/marketmate/splunk/access-token \
    ParameterKey=OpenAIApiKeyParameterName,ParameterValue=/marketmate/openai/api-key \
    ParameterKey=SplunkRealm,ParameterValue=us1 \
    ParameterKey=EnvironmentName,ParameterValue=marketmate
```

Wait for completion:

```bash
aws cloudformation wait stack-create-complete --stack-name marketmate-python-demo
aws cloudformation describe-stacks \
  --stack-name marketmate-python-demo \
  --query "Stacks[0].Outputs"
```

## Add the OpenAI API Key on EC2

Before creating the stack, create encrypted SSM parameters:

```bash
aws ssm put-parameter \
  --name /marketmate/splunk/access-token \
  --type SecureString \
  --value YOUR_SPLUNK_ACCESS_TOKEN \
  --overwrite

aws ssm put-parameter \
  --name /marketmate/openai/api-key \
  --type SecureString \
  --value YOUR_OPENAI_API_KEY \
  --overwrite
```

## Update App Code

The EC2 bootstrap clones the Git repo on first launch. For later updates:

```bash
sudo -u marketmate git -C /opt/marketmate/repo pull --ff-only origin main
sudo systemctl restart marketmate
```

## Tear Down

Delete the stack when finished to avoid charges:

```bash
aws cloudformation delete-stack --stack-name marketmate-python-demo
aws cloudformation wait stack-delete-complete --stack-name marketmate-python-demo
```
