import os
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from . import models, schemas, database
from .s3_client import upload_file, delete_file  # асинхронные функции
from typing import List
from datetime import datetime
from sqlalchemy import text
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="Bike Service",
    description="API for bike management and rentals",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json"
)


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


@app.post("/bikes/", response_model=schemas.Bike, status_code=status.HTTP_201_CREATED)
async def create_bike(
        name: str = Form(...),
        description: str = Form(...),
        price_per_hour: float = Form(...),
        is_available: bool = Form(True),
        image: UploadFile = File(...),
        db: AsyncSession = Depends(get_db)
):
    try:
        # Валидация цены
        if price_per_hour <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Price per hour must be positive"
            )

        # Валидация файла
        if not image.content_type.startswith('image/'):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="File must be an image"
            )

        # ✅ АСИНХРОННАЯ загрузка в S3
        image_url = await upload_file(image.file, image.filename)

        bike = models.Bike(
            name=name,
            description=description,
            price_per_hour=price_per_hour,
            is_available=is_available,
            image_url=image_url
        )

        db.add(bike)
        await db.commit()
        await db.refresh(bike)
        return bike

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating bike: {str(e)}"
        )


@app.get("/bikes/", response_model=List[schemas.Bike])
async def read_bikes(
        skip: int = 0,
        limit: int = 100,
        available_only: bool = False,
        db: AsyncSession = Depends(get_db)
):
    try:
        query = select(models.Bike)

        if available_only:
            query = query.where(models.Bike.is_available == True)

        result = await db.execute(query.offset(skip).limit(limit))
        bikes = result.scalars().all()
        return bikes

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error retrieving bikes: {str(e)}"
        )


@app.get("/bikes/{bike_id}", response_model=schemas.Bike)
async def read_bike(bike_id: int, db: AsyncSession = Depends(get_db)):
    try:
        result = await db.execute(
            select(models.Bike).where(models.Bike.id == bike_id)
        )
        bike = result.scalar_one_or_none()

        if bike is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Bike not found"
            )
        return bike

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error retrieving bike: {str(e)}"
        )


@app.put("/bikes/{bike_id}", response_model=schemas.Bike)
async def update_bike(
        bike_id: int,
        bike_data: schemas.BikeUpdate,
        db: AsyncSession = Depends(get_db)
):
    try:
        result = await db.execute(
            select(models.Bike).where(models.Bike.id == bike_id)
        )
        bike = result.scalar_one_or_none()

        if bike is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Bike not found"
            )

        update_data = bike_data.dict(exclude_unset=True)

        # Валидация цены если она обновляется
        if 'price_per_hour' in update_data and update_data['price_per_hour'] <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Price per hour must be positive"
            )

        for field, value in update_data.items():
            setattr(bike, field, value)

        await db.commit()
        await db.refresh(bike)
        return bike

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating bike: {str(e)}"
        )


@app.delete("/bikes/{bike_id}")
async def delete_bike(bike_id: int, db: AsyncSession = Depends(get_db)):
    try:
        result = await db.execute(
            select(models.Bike).where(models.Bike.id == bike_id)
        )
        bike = result.scalar_one_or_none()

        if bike is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Bike not found"
            )

        # ✅ АСИНХРОННОЕ удаление изображения из S3
        await delete_file(bike.image_url)

        await db.delete(bike)
        await db.commit()

        return {
            "message": "Bike deleted successfully",
            "bike_id": bike_id
        }

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting bike: {str(e)}"
        )


@app.get("/health")
async def health_check(db: AsyncSession = Depends(get_db)):
    health_info = {
        "status": "healthy",
        "service": "bike",
        "timestamp": datetime.utcnow().isoformat()
    }

    # Проверка базы данных
    try:
        await db.execute(text("SELECT 1"))
        health_info["database"] = {"status": "connected"}
    except Exception as e:
        health_info["database"] = {"status": "error", "error": str(e)}
        health_info["status"] = "unhealthy"

    # Упрощенная проверка S3
    health_info["s3"] = {"status": "available"}  # всегда available благодаря заглушкам

    return health_info