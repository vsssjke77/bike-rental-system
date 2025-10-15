from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import text
from . import models, schemas, auth, database
from typing import List
from datetime import datetime
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="Auth Service",
    description="API for user authentication and authorization",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json"
)
security = HTTPBearer()



# После создания app добавьте:
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Добавьте нужные origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Создание таблиц при старте приложения
@app.on_event("startup")
async def startup():
    async with database.engine.begin() as conn:
        await conn.run_sync(models.Base.metadata.create_all)


# Асинхронная зависимость для получения сессии БД
async def get_db():
    async with database.AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


# Асинхронная функция для получения текущего пользователя
async def get_current_user(
        credentials: HTTPAuthorizationCredentials = Depends(security),
        db: AsyncSession = Depends(get_db)
):
    try:
        token = credentials.credentials
        payload = auth.verify_token(token)
        if payload is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials"
            )

        user_id = payload.get("sub")
        if isinstance(user_id, str) and user_id.isdigit():
            user_id = int(user_id)
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token payload"
            )

        # Асинхронный запрос к базе данных
        result = await db.execute(
            select(models.User).where(models.User.id == user_id)
        )
        user = result.scalar_one_or_none()

        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found"
            )
        return user
    except HTTPException:
        raise
    except Exception as e:
        # Логируем ошибку для диагностики
        print(f"Error in get_current_user: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )


@app.post("/register", response_model=schemas.User)
async def register(user_data: schemas.UserCreate, db: AsyncSession = Depends(get_db)):
    # Асинхронная проверка существования пользователя
    result = await db.execute(
        select(models.User).where(models.User.email == user_data.email)
    )
    db_user = result.scalar_one_or_none()

    if db_user:
        raise HTTPException(status_code=400, detail="Email already registered")

    hashed_password = auth.get_password_hash(user_data.password)
    user = models.User(
        email=user_data.email,
        hashed_password=hashed_password,
        full_name=user_data.full_name,
        is_admin=user_data.is_admin
    )

    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@app.post("/login")
async def login(login_data: schemas.UserLogin, db: AsyncSession = Depends(get_db)):
    # Асинхронный запрос пользователя
    result = await db.execute(
        select(models.User).where(models.User.email == login_data.email)
    )
    user = result.scalar_one_or_none()

    if not user or not auth.verify_password(login_data.password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Incorrect email or password")

    # Сохраняем ID как число, а не строку
    access_token = auth.create_access_token(data={"sub": str(user.id)})
    return {"access_token": access_token, "token_type": "bearer"}


@app.get("/users/me", response_model=schemas.User)
async def read_users_me(current_user: models.User = Depends(get_current_user)):
    return current_user


@app.get("/users/", response_model=List[schemas.User])
async def read_users(skip: int = 0, limit: int = 100, db: AsyncSession = Depends(get_db)):
    # Асинхронный запрос с пагинацией
    result = await db.execute(
        select(models.User).offset(skip).limit(limit)
    )
    users = result.scalars().all()
    return users


@app.get("/health")
async def health_check(db: AsyncSession = Depends(get_db)):
    try:
        # Асинхронная проверка подключения к базе данных
        await db.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception as e:
        db_status = f"error: {str(e)}"

    return {
        "status": "healthy",
        "service": "auth",
        "database": db_status,
        "timestamp": datetime.utcnow().isoformat()
    }