from datetime import datetime
from sqlalchemy import Column, DateTime, Integer, String, Text, ForeignKey
from sqlalchemy.orm import declarative_base, relationship
Base = declarative_base()
class Project(Base):
    __tablename__='projects'
    id=Column(Integer, primary_key=True); name=Column(String(200), nullable=False); upload_date=Column(DateTime, default=datetime.utcnow)
    file_count=Column(Integer, default=0); file_list=Column(Text, default=''); status=Column(String(50), default='uploaded'); generated_documentation=Column(Text, default='')
    versions=relationship('ProjectVersion', back_populates='project', cascade='all, delete-orphan'); documentation_versions=relationship('DocumentationVersion', back_populates='project', cascade='all, delete-orphan')
class ProjectVersion(Base):
    __tablename__='project_versions'
    id=Column(Integer, primary_key=True); project_id=Column(Integer, ForeignKey('projects.id'), nullable=False); created_at=Column(DateTime, default=datetime.utcnow); manifest=Column(Text, nullable=False); snapshot_hash=Column(String(64), nullable=False)
    project=relationship('Project', back_populates='versions')
class ChangeReport(Base):
    __tablename__='change_reports'
    id=Column(Integer, primary_key=True); project_id=Column(Integer, ForeignKey('projects.id'), nullable=False); previous_version_id=Column(Integer); current_version_id=Column(Integer); changes=Column(Text, nullable=False); impact=Column(Text, nullable=False); created_at=Column(DateTime, default=datetime.utcnow)

class DocumentationVersion(Base):
    __tablename__='documentation_versions'
    id=Column(Integer, primary_key=True); project_id=Column(Integer, ForeignKey('projects.id'), nullable=False); project_version_id=Column(Integer, ForeignKey('project_versions.id')); doc_type=Column(String(80), default='README'); content=Column(Text, nullable=False); status=Column(String(40), default='CURRENT'); created_at=Column(DateTime, default=datetime.utcnow)
    project=relationship('Project', back_populates='documentation_versions')
