"""Script to inspect and cleanly remove test fixture providers from the development database.

Usage:
    python scripts/cleanup_dev_fixtures.py          # Dry run (preview only)
    python scripts/cleanup_dev_fixtures.py --confirm # Apply changes
"""
import asyncio
import sys
from sqlalchemy import select, update, delete
from app.db.session import AsyncSessionLocal
from app.models.sql_models import LLMProvider, LLMSettings
from app.core.config import settings


async def run_cleanup(confirm: bool = False):
    print("=" * 60)
    print("Dev Database Fixture Cleanup Tool")
    print(f"Target Database: {settings.DATABASE_URL.split('@')[-1]}")
    print("=" * 60)

    async with AsyncSessionLocal() as session:
        # 1. Fetch current settings
        res = await session.execute(select(LLMSettings).where(LLMSettings.id == 1))
        current_settings = res.scalars().first()
        if not current_settings:
            print("ERROR: llm_settings table is empty!")
            return

        # 2. Fetch all providers
        res = await session.execute(select(LLMProvider))
        all_providers = res.scalars().all()

        print(f"\nFound {len(all_providers)} total providers in database:")
        fixtures_to_delete = []
        default_provider = None

        for p in all_providers:
            is_fixture = any(
                p.name.startswith(prefix)
                for prefix in ["Stream Reload Prov", "Clear Key Prov", "Active Key Prov", "Test Provider"]
            )
            is_default = (
                "default" in p.name.lower()
                or p.base_url == settings.LLM_BASE_URL
                or p.default_model == settings.ANSWER_MODEL
            )
            marker = "[FIXTURE TO REMOVE]" if is_fixture else ("[DEFAULT / LIVE]" if is_default else "[CUSTOM]")
            print(f" - {marker} ID: {p.id} | Name: '{p.name}' | URL: {p.base_url} | Model: {p.default_model}")

            if is_fixture:
                fixtures_to_delete.append(p)
            elif is_default and not default_provider:
                default_provider = p

        if not default_provider and all_providers:
            # Fallback to the first non-fixture
            non_fixtures = [p for p in all_providers if p not in fixtures_to_delete]
            if non_fixtures:
                default_provider = non_fixtures[0]

        print("\n--- Plan Summary ---")
        if default_provider:
            print(f"1. Restore llm_settings:")
            print(f"   - active_provider_id: {current_settings.active_provider_id} -> {default_provider.id} ('{default_provider.name}')")
            print(f"   - active_model: '{current_settings.active_model}' -> '{default_provider.default_model}'")
            print(f"   - fallback_provider_id: {current_settings.fallback_provider_id} -> None")
            print(f"   - fallback_model: '{current_settings.fallback_model}' -> None")
        else:
            print("1. No default provider found to restore settings to!")

        print(f"2. Delete {len(fixtures_to_delete)} fixture provider(s):")
        for f in fixtures_to_delete:
            print(f"   - ID: {f.id} ('{f.name}')")

        if not confirm:
            print("\n[DRY RUN ONLY] No changes were made to the database.")
            print("To execute this cleanup, run:")
            print("   python scripts/cleanup_dev_fixtures.py --confirm")
            print("=" * 60)
            return

        # Execute changes
        if default_provider:
            await session.execute(
                update(LLMSettings)
                .where(LLMSettings.id == 1)
                .values(
                    active_provider_id=default_provider.id,
                    active_model=default_provider.default_model,
                    fallback_provider_id=None,
                    fallback_model=None,
                    version=current_settings.version + 1,
                )
            )

        for f in fixtures_to_delete:
            await session.execute(delete(LLMProvider).where(LLMProvider.id == f.id))

        await session.commit()
        print("\n[SUCCESS] Dev database cleaned up successfully!")
        print("Restored active provider to default and deleted all leftover test fixtures.")
        print("=" * 60)


if __name__ == "__main__":
    confirm_flag = "--confirm" in sys.argv
    asyncio.run(run_cleanup(confirm=confirm_flag))
