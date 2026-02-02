from app.jwt import config
token  = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI2OTJmZGNmOTcyYzg3ZTUxMjMyNTZlYzAiLCJ0eXBlIjoiYWNjZXNzIiwiaWF0IjoxNzY2MzAxOTQxLCJleHAiOjE3NjYzMDM3NDEsImlzcyI6InNwYXJrLWFwaSJ9.xtshUlC8bA4FJDeuqNsZCw7yz03wUTv1f4oMTVmzD5g"

def check():
  data = config.decode_token(token)
  print("data", data)

check()

