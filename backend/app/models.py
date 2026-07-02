from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, func, Float
from sqlalchemy.orm import relationship
from .database import Base

# ==========================================
# 1. USERS TABLE
# ==========================================
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    password = Column(String) 
    role = Column(String, default="buyer")
    
    # --- NEW ATTRIBUTE ---
    # Defaulting to 0.0 or a starting bonus like 100.0 for testing
    credits = Column(Float, default=0.0) 
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # RELATIONSHIPS
    jobs = relationship("Job", back_populates="owner")
    agents = relationship("Agent", back_populates="owner")

# ==========================================
# 2. AGENTS TABLE (Previously Sellers)
# ==========================================
class Agent(Base):
    __tablename__ = "agents"

    id = Column(String, primary_key=True, index=True) # e.g. "agent_xyz"
    owner_id = Column(Integer, ForeignKey("users.id"))
    
    status = Column(String, default="OFFLINE")
    gpu_model = Column(String, nullable=True)
    ram_total = Column(String, nullable=True)
    
    last_heartbeat = Column(DateTime(timezone=True), server_default=func.now())

    # RELATIONSHIPS
    owner = relationship("User", back_populates="agents")
    subtasks = relationship("Subtask", back_populates="assigned_agent")


# ==========================================
# 3. JOBS TABLE
# ==========================================
class Job(Base):
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String)
    status = Column(String, default="PROCESSING")

    # FILE URLs
    original_code_url = Column(String)
    original_req_url = Column(String)
    original_data_url = Column(String)
    
    # AGGREGATION
    final_result_url = Column(String, nullable=True)
    # L2 norm of (weighted FedAvg - uniform avg). Quantifies how much
    # data distribution skew affected the final model.
    convergence_delta = Column(Float, nullable=True)

    owner_id = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # RELATIONSHIPS
    owner = relationship("User", back_populates="jobs")
    subtasks = relationship("Subtask", back_populates="job")


# ==========================================
# 4. SUBTASKS TABLE
# ==========================================
class Subtask(Base):
    __tablename__ = "subtasks"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"))
    assigned_to = Column(String, ForeignKey("agents.id"), nullable=True)

    status = Column(String, default="PENDING")
    chunk_file_url = Column(String)
    result_file_url = Column(String, nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # Number of rows in this chunk — used for weighted FedAvg.
    # Each worker's model is weighted by (its rows / total rows across all workers).
    chunk_row_count = Column(Integer, nullable=True)

    # RELATIONSHIPS
    job = relationship("Job", back_populates="subtasks")
    assigned_agent = relationship("Agent", back_populates="subtasks")