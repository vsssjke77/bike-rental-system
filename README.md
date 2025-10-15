# Bike Rental System

Микросервисная система аренды велосипедов с FastAPI и PostgreSQL.

## Архитектура

- **auth-service** - аутентификация и авторизация
- **bike-service** - управление велосипедами
- **rental-service** - управление арендами  
- **frontend** - веб-интерфейс(html)

## Технологии

- FastAPI
- PostgreSQL
- SQLAlchemy
- JWT
- Docker
- Selectel S3

## Запуск

1. Клонируйте репозиторий 
2. Создайте `.env` файл в корне </br>
3. Запустите: `docker-compose up -d`
<details> <summary>📁 Пример .env файла (нажмите чтобы развернуть)</summary>
# PostgreSQL Configuration
POSTGRES_USER=postgres
POSTGRES_PASSWORD=your_secure_password_here
POSTGRES_HOST=localhost
POSTGRES_PORT=5432

# Database URLs
AUTH_DB_URL=postgresql://postgres:your_secure_password_here@postgres:5432/auth_db
BIKE_DB_URL=postgresql://postgres:your_secure_password_here@postgres:5432/bike_db
RENTAL_DB_URL=postgresql://postgres:your_secure_password_here@postgres:5432/rental_db

# JWT Configuration
JWT_SECRET_KEY=your_super_secret_jwt_key_change_in_production
JWT_ALGORITHM=HS256

# AWS S3 Configuration
AWS_ACCESS_KEY_ID=your_s3_access_key_here
AWS_SECRET_ACCESS_KEY=your_s3_secret_key_here
AWS_REGION=ru-7
S3_ENDPOINT_URL=https://s3.ru-7.storage.selcloud.ru
S3_BUCKET_NAME=your-bucket-name
S3_ACCESS_DOMAIN=your-domain.selstorage.ru
</details>


## API Documentation

- Auth: http://localhost:8001/docs
- Bike: http://localhost:8002/docs  
- Rental: http://localhost:8003/docs