import asyncio

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from . import models, schemas, database
from typing import List
import aiohttp
import requests
from datetime import datetime, timezone
from sqlalchemy import text
import logging
from fastapi.middleware.cors import CORSMiddleware

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Rental Service",
    description="API for bike rental management",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json"
)

security = HTTPBearer()


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


# Функция для проверки авторизации через auth-service
async def verify_auth_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Проверяет токен через auth-service"""
    try:
        token = credentials.credentials
        logger.info(f"Verifying token: {token[:20]}...")  # Логируем начало проверки

        async with aiohttp.ClientSession() as session:
            logger.info("Making request to auth-service...")

            async with session.get(
                    "http://auth-service:8000/users/me",
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=10
            ) as response:

                logger.info(f"Auth service response status: {response.status}")

                if response.status == 200:
                    user_data = await response.json()
                    logger.info(f"User authenticated: {user_data['id']}")
                    return user_data
                else:
                    error_text = await response.text()
                    logger.error(f"Auth service error: {response.status} - {error_text}")
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Invalid authentication credentials"
                    )

    except aiohttp.ClientConnectorError as e:
        logger.error(f"Cannot connect to auth service: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service unavailable"
        )
    except asyncio.TimeoutError:
        logger.error("Auth service timeout")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service timeout"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in auth verification: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Authentication error"
        )


# Функция для получения текущего пользователя
async def get_current_user(user_data: dict = Depends(verify_auth_token)):
    """Возвращает данные текущего пользователя"""
    return user_data


# Асинхронная функция для получения информации о велосипеде
async def get_bike_info(bike_id: int):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://bike-service:8000/bikes/{bike_id}") as response:
                if response.status == 200:
                    return await response.json()
    except Exception:
        pass
    return None


# Асинхронная функция для обновления статуса велосипеда
async def update_bike_status(bike_id: int, is_available: bool):
    """Обновляет статус доступности велосипеда"""
    try:
        async with aiohttp.ClientSession() as session:
            update_data = {"is_available": is_available}
            async with session.put(
                    f"http://bike-service:8000/bikes/{bike_id}",
                    json=update_data
            ) as response:
                if response.status == 200:
                    logger.info(f"Bike {bike_id} status updated to available={is_available}")
                    return True
                else:
                    logger.error(f"Failed to update bike status: HTTP {response.status}")
                    return False
    except Exception as e:
        logger.error(f"Error updating bike status: {e}")
        return False


async def calculate_actual_price(bike_id: int, start_time: datetime, actual_end_time: datetime) -> float:
    """Пересчитывает стоимость аренды на основе фактического времени"""
    try:
        bike_info = await get_bike_info(bike_id)
        if not bike_info:
            logger.warning(f"Bike {bike_id} not found for price calculation, using original price")
            return None

        # Рассчитываем фактическое время использования в часах
        actual_hours = (actual_end_time - start_time).total_seconds() / 3600

        # Пересчитываем стоимость
        price_per_hour = bike_info["price_per_hour"]
        actual_price = actual_hours * price_per_hour

        logger.info(f"Price recalculated: {actual_hours:.2f}h * {price_per_hour} = {actual_price:.2f}")
        return actual_price

    except Exception as e:
        logger.error(f"Error calculating actual price: {e}")
        return None


@app.post("/rentals/", response_model=schemas.Rental)
async def create_rental(
        rental_data: schemas.RentalCreate,
        db: AsyncSession = Depends(get_db),
        current_user: dict = Depends(get_current_user)
):
    try:
        # Проверяем, что пользователь арендует для себя
        if rental_data.user_id != current_user["id"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only create rentals for yourself"
            )

        # Check if bike exists and is available
        bike_info = await get_bike_info(rental_data.bike_id)
        if not bike_info:
            raise HTTPException(status_code=404, detail="Bike not found")
        if not bike_info["is_available"]:
            raise HTTPException(status_code=400, detail="Bike is not available")

        # Дополнительная проверка на случай, если валидатор не сработал
        start_time = rental_data.start_time
        end_time = rental_data.end_time

        if start_time.tzinfo is not None:
            start_time = start_time.astimezone(timezone.utc).replace(tzinfo=None)
        if end_time.tzinfo is not None:
            end_time = end_time.astimezone(timezone.utc).replace(tzinfo=None)

        # Проверка, что start_time раньше end_time
        if start_time >= end_time:
            raise HTTPException(status_code=400, detail="Start time must be before end time")

        # Проверка, что start_time не в прошлом
        if start_time < datetime.utcnow():
            start_time = datetime.utcnow()

        # Calculate total price (ориентировочная стоимость)
        hours = (end_time - start_time).total_seconds() / 3600
        total_price = hours * bike_info["price_per_hour"]

        rental = models.Rental(
            user_id=rental_data.user_id,
            bike_id=rental_data.bike_id,
            start_time=start_time,
            end_time=end_time,
            total_price=total_price,
            status="active",
            created_at=datetime.utcnow()  # naive datetime
        )

        db.add(rental)
        await db.commit()
        await db.refresh(rental)

        # ✅ ОБНОВЛЯЕМ СТАТУС ВЕЛОСИПЕДА НА "недоступен"
        update_success = await update_bike_status(rental_data.bike_id, False)
        if not update_success:
            logger.warning(f"Failed to update bike {rental_data.bike_id} status to unavailable")

        return rental

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Error creating rental: {str(e)}"
        )


@app.get("/rentals/", response_model=List[schemas.Rental])
async def read_rentals(
        skip: int = 0,
        limit: int = 100,
        db: AsyncSession = Depends(get_db),
        current_user: dict = Depends(get_current_user)  # ✅ ДОБАВЛЕНО
):
    try:
        # Только администраторы могут видеть все аренды
        if not current_user.get("is_admin", False):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only administrators can view all rentals"
            )

        result = await db.execute(
            select(models.Rental).offset(skip).limit(limit)
        )
        rentals = result.scalars().all()
        return rentals
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error retrieving rentals: {str(e)}"
        )


@app.get("/rentals/user/{user_id}", response_model=List[schemas.Rental])
async def read_user_rentals(
        user_id: int,
        db: AsyncSession = Depends(get_db),
        current_user: dict = Depends(get_current_user)  # ✅ ДОБАВЛЕНО
):
    try:
        # Пользователи могут видеть только свои аренды
        if user_id != current_user["id"] and not current_user.get("is_admin", False):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only view your own rentals"
            )

        result = await db.execute(
            select(models.Rental).where(models.Rental.user_id == user_id)
        )
        rentals = result.scalars().all()
        return rentals
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error retrieving user rentals: {str(e)}"
        )


@app.put("/rentals/{rental_id}/complete", response_model=schemas.Rental)
async def complete_rental(
        rental_id: int,
        db: AsyncSession = Depends(get_db),
        current_user: dict = Depends(get_current_user)  # ✅ ДОБАВЛЕНО
):
    try:
        result = await db.execute(
            select(models.Rental).where(models.Rental.id == rental_id)
        )
        rental = result.scalar_one_or_none()

        if rental is None:
            raise HTTPException(status_code=404, detail="Rental not found")

        # Проверяем права доступа
        if rental.user_id != current_user["id"] and not current_user.get("is_admin", False):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only complete your own rentals"
            )

        if rental.status == "completed":
            raise HTTPException(status_code=400, detail="Rental already completed")

        # ✅ ПЕРЕСЧИТЫВАЕМ СТОИМОСТЬ НА ОСНОВЕ ФАКТИЧЕСКОГО ВРЕМЕНИ
        actual_end_time = datetime.utcnow()
        actual_price = await calculate_actual_price(
            rental.bike_id,
            rental.start_time,
            actual_end_time
        )

        # Обновляем аренду
        rental.status = "completed"
        rental.actual_end_time = actual_end_time
        if actual_price is not None:
            rental.total_price = actual_price
            logger.info(f"Rental {rental_id} price updated to {actual_price:.2f}")

        await db.commit()
        await db.refresh(rental)

        # ✅ ОБНОВЛЯЕМ СТАТУС ВЕЛОСИПЕДА НА "доступен"
        update_success = await update_bike_status(rental.bike_id, True)
        if not update_success:
            logger.warning(f"Failed to update bike {rental.bike_id} status to available")

        return rental

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Error completing rental: {str(e)}"
        )


@app.put("/rentals/{rental_id}/cancel", response_model=schemas.Rental)
async def cancel_rental(
        rental_id: int,
        db: AsyncSession = Depends(get_db),
        current_user: dict = Depends(get_current_user)  # ✅ ДОБАВЛЕНО
):
    """Дополнительный endpoint для отмены аренды"""
    try:
        result = await db.execute(
            select(models.Rental).where(models.Rental.id == rental_id)
        )
        rental = result.scalar_one_or_none()

        if rental is None:
            raise HTTPException(status_code=404, detail="Rental not found")

        # Проверяем права доступа
        if rental.user_id != current_user["id"] and not current_user.get("is_admin", False):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only cancel your own rentals"
            )

        if rental.status != "active":
            raise HTTPException(status_code=400, detail="Only active rentals can be canceled")

        # ✅ ПЕРЕСЧИТЫВАЕМ СТОИМОСТЬ ДЛЯ ОТМЕНЕННОЙ АРЕНДЫ
        actual_end_time = datetime.utcnow()
        actual_price = await calculate_actual_price(
            rental.bike_id,
            rental.start_time,
            actual_end_time
        )

        # Штраф 50% за отмену
        if actual_price is not None:
            actual_price *= 0.5
            rental.total_price = actual_price
            logger.info(f"Canceled rental {rental_id} price updated to {actual_price:.2f}")

        rental.status = "canceled"
        rental.actual_end_time = actual_end_time

        await db.commit()
        await db.refresh(rental)

        # ✅ ОБНОВЛЯЕМ СТАТУС ВЕЛОСИПЕДА НА "доступен" при отмене
        update_success = await update_bike_status(rental.bike_id, True)
        if not update_success:
            logger.warning(f"Failed to update bike {rental.bike_id} status to available")

        return rental

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Error canceling rental: {str(e)}"
        )


@app.get("/rentals/{rental_id}/price-breakdown")
async def get_price_breakdown(
        rental_id: int,
        db: AsyncSession = Depends(get_db),
        current_user: dict = Depends(get_current_user)  # ✅ ДОБАВЛЕНО
):
    """Получить детализацию стоимости аренды"""
    try:
        result = await db.execute(
            select(models.Rental).where(models.Rental.id == rental_id)
        )
        rental = result.scalar_one_or_none()

        if rental is None:
            raise HTTPException(status_code=404, detail="Rental not found")

        # Проверяем права доступа
        if rental.user_id != current_user["id"] and not current_user.get("is_admin", False):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only view your own rental details"
            )

        bike_info = await get_bike_info(rental.bike_id)
        if not bike_info:
            raise HTTPException(status_code=404, detail="Bike information not available")

        # Расчеты времени
        planned_hours = (rental.end_time - rental.start_time).total_seconds() / 3600
        planned_price = planned_hours * bike_info["price_per_hour"]

        breakdown = {
            "rental_id": rental_id,
            "bike_id": rental.bike_id,
            "bike_name": bike_info.get("name", "Unknown"),
            "price_per_hour": bike_info["price_per_hour"],
            "planned": {
                "start_time": rental.start_time,
                "end_time": rental.end_time,
                "hours": round(planned_hours, 2),
                "price": round(planned_price, 2)
            },
            "status": rental.status
        }

        # Если аренда завершена или отменена, добавляем фактические данные
        if rental.actual_end_time:
            actual_hours = (rental.actual_end_time - rental.start_time).total_seconds() / 3600
            actual_price = actual_hours * bike_info["price_per_hour"]

            breakdown["actual"] = {
                "start_time": rental.start_time,
                "end_time": rental.actual_end_time,
                "hours": round(actual_hours, 2),
                "price": round(rental.total_price, 2)
            }

        return breakdown

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error getting price breakdown: {str(e)}"
        )


# Health check остается без авторизации
@app.get("/health")
async def health_check(db: AsyncSession = Depends(get_db)):
    health_info = {
        "status": "healthy",
        "service": "rental",
        "timestamp": datetime.utcnow().isoformat()
    }

    # Проверка базы данных
    try:
        start_time = datetime.utcnow()
        await db.execute(text("SELECT 1"))
        db_response_time = (datetime.utcnow() - start_time).total_seconds() * 1000
        health_info["database"] = {
            "status": "connected",
            "response_time_ms": round(db_response_time, 2)
        }
    except Exception as e:
        health_info["database"] = {
            "status": "error",
            "error": str(e)
        }
        health_info["status"] = "unhealthy"

    # Проверка доступности bike service с aiohttp
    try:
        start_time = datetime.utcnow()
        async with aiohttp.ClientSession() as session:
            async with session.get("http://bike-service:8000/health", timeout=5) as response:
                bike_response_time = (datetime.utcnow() - start_time).total_seconds() * 1000

                if response.status == 200:
                    bike_data = await response.json()
                    health_info["bike_service"] = {
                        "status": bike_data.get("status", "unknown"),
                        "response_time_ms": round(bike_response_time, 2),
                        "details": bike_data
                    }
                else:
                    health_info["bike_service"] = {
                        "status": "error",
                        "error": f"HTTP {response.status}",
                        "response_time_ms": round(bike_response_time, 2)
                    }
                    health_info["status"] = "degraded"

    except Exception as e:
        health_info["bike_service"] = {
            "status": "error",
            "error": str(e)
        }
        health_info["status"] = "degraded"

    return health_info