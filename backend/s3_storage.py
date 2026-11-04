import boto3

BUCKET_NAME = "cloudvault-storage-prashant-2026"

s3 = boto3.client(
    "s3",
    region_name="ap-south-1"
)


def upload_file(file, key):
    s3.upload_fileobj(file, BUCKET_NAME, key)


def download_file(key):
    return s3.get_object(
        Bucket=BUCKET_NAME,
        Key=key
    )


def delete_file(key):
    s3.delete_object(
        Bucket=BUCKET_NAME,
        Key=key
    )


def copy_file(old_key, new_key):
    s3.copy_object(
        Bucket=BUCKET_NAME,
        CopySource={
            "Bucket": BUCKET_NAME,
            "Key": old_key
        },
        Key=new_key
    )