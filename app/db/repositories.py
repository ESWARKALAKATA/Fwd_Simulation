from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import or_, and_
from app.db.models import Customer, EngineInput, RuleTrigger, Decision, SourceLimit, AuditLog

class DataRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_customer_by_name(self, name: str):
        result = await self.db.execute(select(Customer).where(Customer.full_name.ilike(f"%{name}%")))
        return result.scalars().first()

    async def get_all_customers(self):
        result = await self.db.execute(select(Customer))
        return result.scalars().all()

    async def get_source_limit(self, source_system: str):
        result = await self.db.execute(select(SourceLimit).where(SourceLimit.source_system == source_system))
        return result.scalars().first()

    async def get_all_source_limits(self):
        result = await self.db.execute(select(SourceLimit))
        return result.scalars().all()

    async def get_engine_input_by_id(self, input_id: int):
        result = await self.db.execute(select(EngineInput).where(EngineInput.id == input_id))
        return result.scalars().first()

    async def get_engine_inputs_by_customer(self, customer_id: int):
        result = await self.db.execute(select(EngineInput).where(EngineInput.customer_id == customer_id))
        return result.scalars().all()

    async def get_rule_triggers_by_input(self, input_id: int):
        result = await self.db.execute(select(RuleTrigger).where(RuleTrigger.input_id == input_id))
        return result.scalars().all()

    async def get_decision_by_input(self, input_id: int):
        result = await self.db.execute(select(Decision).where(Decision.input_id == input_id))
        return result.scalars().first()

    async def search_by_rule_code(self, rule_code: str):
        result = await self.db.execute(select(RuleTrigger).where(RuleTrigger.rule_code == rule_code))
        return result.scalars().all()
        """
        DANGEROUS: For the agent to run generated SQL.
        In production, use read-only user or strict parsing.
        """
        # This is just a placeholder for the "Plan -> SQL" flow
        # We won't actually implement arbitrary SQL execution for safety in this stub
        # unless explicitly requested. The prompt says "Execute the necessary Postgres queries via the DB layer".
        # We'll stick to defined methods for now to be safe, or return mock data.
        return {"info": "Raw SQL execution disabled in Phase 1 stub."}
