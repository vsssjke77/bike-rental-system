from jose import JWTError, jwt
import bcrypt
from datetime import datetime, timedelta
import os

SECRET_KEY = os.getenv("JWT_SECRET_KEY", "your-secret-key")
ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# Удаляем CryptContext и используем bcrypt напрямую

def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        # Преобразуем пароли в bytes
        plain_password_bytes = plain_password.encode('utf-8')
        hashed_password_bytes = hashed_password.encode('utf-8')
        return bcrypt.checkpw(plain_password_bytes, hashed_password_bytes)
    except Exception:
        return False

def get_password_hash(password: str) -> str:
    # Преобразуем пароль в bytes
    password_bytes = password.encode('utf-8')
    # Генерируем соль и хешируем пароль
    hashed_bytes = bcrypt.hashpw(password_bytes, bcrypt.gensalt())
    # Преобразуем обратно в строку для хранения в БД
    return hashed_bytes.decode('utf-8')

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def verify_token(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        print(f"Token verified successfully for user {payload.get('sub')}")
        return payload
    except JWTError as e:
        print(f"JWT Error: {e}")
        return None
    except Exception as e:
        print(f"Token verification error: {e}")
        return None