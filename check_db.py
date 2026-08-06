import asyncio
import asyncpg


async def main() -> None:
    conn = await asyncpg.connect(
        user="poke", password="poke", database="pokecard",
        host="localhost", port=5432,
    )
    version = await conn.fetchval("SHOW server_version")
    nulls_ok = int(version.split(".")[0]) >= 15
    print(f"PostgreSQL {version}")
    print(f"NULLS NOT DISTINCT 지원: {nulls_ok}")
    await conn.close()


asyncio.run(main())