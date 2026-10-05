"""Admin user seeding script.

Creates the initial admin account using ADMIN_EMAIL and ADMIN_PASSWORD.
Can be executed as a standalone CLI script or called at startup.
Admins are NEVER created through the API.
"""
import asyncio
import sys
from sqlalchemy import select
from app.db.session import AsyncSessionLocal
from app.models.sql_models import User
from app.core.security import hash_password
from app.core.config import settings
from app.core.logger import logger


async def seed_admin(email: str = None, password: str = None) -> bool:
    """Idempotently seed the initial administrator user."""
    admin_email = email or settings.ADMIN_EMAIL
    admin_pass = password or (
        settings.ADMIN_PASSWORD.get_secret_value() if settings.ADMIN_PASSWORD else None
    )

    if not admin_email or not admin_pass:
        logger.warning("Admin seeding skipped: ADMIN_EMAIL or ADMIN_PASSWORD not configured.")
        return False

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.email == admin_email.lower())
        )
        user = result.scalar_one_or_none()

        if user:
            user.password_hash = hash_password(admin_pass)
            if user.role != "admin":
                user.role = "admin"
                logger.info(f"Promoted existing user {admin_email} to admin role and updated password.")
            else:
                logger.info(f"Admin user {admin_email} password updated.")
            await session.commit()
            return True

        # Create new admin user
        new_admin = User(
            email=admin_email.lower(),
            password_hash=hash_password(admin_pass),
            role="admin",
            is_active=True,
        )
        session.add(new_admin)
        await session.commit()
        logger.info(f"Successfully seeded admin account: {admin_email} (Role: admin)")
        return True


def main():
    """CLI entrypoint for scripts.seed_admin."""
    logger.info("Running admin seed script...")
    success = asyncio.run(seed_admin())
    if not success:
        sys.exit(1)
    logger.info("Admin seeding complete.")


if __name__ == "__main__":
    main()
