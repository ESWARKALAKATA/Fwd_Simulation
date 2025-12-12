from sqlalchemy import Column, Integer, String, Float, Boolean, ForeignKey, DateTime, Text, Numeric
from sqlalchemy.orm import declarative_base, relationship
from datetime import datetime

Base = declarative_base()

class Customer(Base):
    __tablename__ = "customers"
    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(Text, nullable=False, index=True)
    risk_score = Column(Integer, default=0)
    pep_flag = Column(Boolean, default=False)
    status = Column(Text, default="active")
    
    engine_inputs = relationship("EngineInput", back_populates="customer")

class SourceLimit(Base):
    __tablename__ = "source_limits"
    source_system = Column(Text, primary_key=True)
    limit_amount = Column(Numeric, nullable=False)

class EngineInput(Base):
    __tablename__ = "engine_inputs"
    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"))
    source_system = Column(Text)
    indicator = Column(Text)
    schema_code = Column(Text)
    model_score = Column(Integer)
    card_score = Column(Integer)
    amount = Column(Numeric)
    currency = Column(Text, default="USD")
    created_at = Column(DateTime, default=datetime.utcnow)
    
    customer = relationship("Customer", back_populates="engine_inputs")
    rule_triggers = relationship("RuleTrigger", back_populates="engine_input")
    decisions = relationship("Decision", back_populates="engine_input")
    audit_logs = relationship("AuditLog", back_populates="engine_input")

class RuleTrigger(Base):
    __tablename__ = "rule_triggers"
    id = Column(Integer, primary_key=True, index=True)
    input_id = Column(Integer, ForeignKey("engine_inputs.id"))
    rule_code = Column(Text)
    triggered_at = Column(DateTime, default=datetime.utcnow)
    
    engine_input = relationship("EngineInput", back_populates="rule_triggers")

class Decision(Base):
    __tablename__ = "decisions"
    id = Column(Integer, primary_key=True, index=True)
    input_id = Column(Integer, ForeignKey("engine_inputs.id"))
    final_decision = Column(Text)
    combined_score = Column(Integer)
    action = Column(Text)
    decided_at = Column(DateTime, default=datetime.utcnow)
    
    engine_input = relationship("EngineInput", back_populates="decisions")

class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True, index=True)
    input_id = Column(Integer, ForeignKey("engine_inputs.id"))
    step = Column(Text)
    detail = Column(Text)
    logged_at = Column(DateTime, default=datetime.utcnow)
    
    engine_input = relationship("EngineInput", back_populates="audit_logs")

