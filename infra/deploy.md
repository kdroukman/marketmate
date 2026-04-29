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
- SSH is opened only to the `SshIngressCidr` parameter and requires an existing EC2 key pair.
- The app port defaults to `5273`.
- The Splunk Distribution of OpenTelemetry Collector is installed using Splunk's Linux installer script.
- The app runs under `opentelemetry-instrument` and exports OTLP to the local collector at `http://127.0.0.1:4318`. The OTLP HTTP exporter appends signal paths such as `/v1/traces`.
- The app and collector set `deployment.environment=marketmate` by default.
- The app uses OpenAI Agents SDK and Splunk zero-code GenAI instrumentation via `splunk-otel-instrumentation-openai-agents`.
- The app venv uses Python 3.11 because Splunk AI Agent Monitoring requires Python 3.10+ and Amazon Linux 2023's system Python is 3.9.
- Splunk Observability, Splunk Cloud HEC, and OpenAI secrets are read from encrypted SSM SecureString parameters at boot.
- Observability telemetry uses the Splunk Observability access token and realm `us1`.
- GenAI evaluation/log events use the separate Splunk Cloud Platform HEC token and HEC endpoint through the collector `splunk_hec` exporter/logs pipeline.

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
    ParameterKey=SshIngressCidr,ParameterValue=YOUR_IP/32 \
    ParameterKey=KeyName,ParameterValue=YOUR_KEY_PAIR_NAME \
    ParameterKey=SplunkAccessTokenParameterName,ParameterValue=/marketmate/splunk/access-token \
    ParameterKey=OpenAIApiKeyParameterName,ParameterValue=/marketmate/openai/api-key \
    ParameterKey=SplunkHecTokenParameterName,ParameterValue=/marketmate/splunk/hec-token \
    ParameterKey=SplunkHecEndpoint,ParameterValue=https://http-inputs-shw-playground.splunkcloud.com/services/collector \
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

aws ssm put-parameter \
  --name /marketmate/splunk/hec-token \
  --type SecureString \
  --value YOUR_SPLUNK_CLOUD_HEC_TOKEN \
  --overwrite
```

The EC2 bootstrap passes the HEC settings to the Splunk OTel Collector installer:

```bash
--hec-token "$SPLUNK_HEC_TOKEN"
--hec-url "https://http-inputs-shw-playground.splunkcloud.com/services/collector"
```

It also writes `SPLUNK_HEC_TOKEN` and `SPLUNK_HEC_URL` into `/etc/otel/collector/splunk-otel-collector.conf`. The default Linux agent configuration includes the `splunk_hec` exporter in the logs pipeline, which is the path Splunk uses for instrumentation-side GenAI evaluation events.

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
