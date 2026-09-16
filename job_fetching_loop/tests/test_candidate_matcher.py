"""Tests for Muhammad Usama Candidate CV Matcher & Precision Filtering."""
import pytest
from src.matcher import is_blacklisted_title, match_usama_cv
from src.models import RawJob, ai_keyword_matches


class TestUserReportedMismatches:
    """Verifies that the non-AI, sales, and unrelated tech stack jobs reported by the user are 100% rejected."""

    def test_rejects_client_success_manager(self):
        title = "Client Success Manager"
        desc = "We are an AI customer experience platform transforming support with LLMs."
        is_match, score, label = match_usama_cv(title, description=desc)
        assert not is_match
        assert score == 0
        assert "blacklisted_role" in label

    def test_rejects_bilingual_channel_account_manager(self):
        title = "Bilingual Channel Account Manager, Arabic (MEA) - UK"
        desc = "Manage enterprise partner accounts for our high-growth AI software suite."
        is_match, score, label = match_usama_cv(title, description=desc)
        assert not is_match
        assert score == 0
        assert "blacklisted_role" in label

    def test_rejects_senior_vue_developer(self):
        title = "Senior Vue Developer"
        desc = "Build dynamic frontends using Vue 3 and Pinia for an AI analytics startup."
        is_match, score, label = match_usama_cv(title, description=desc)
        assert not is_match
        assert score == 0
        assert "unrelated_stack" in label

    def test_rejects_senior_java_and_react_developer(self):
        title = "Senior Java & React Developer"
        desc = "Develop scalable Spring Boot backend and React microfrontends connecting to ML pipelines."
        is_match, score, label = match_usama_cv(title, description=desc)
        assert not is_match
        assert score == 0
        assert "unrelated_stack" in label

    def test_rejects_senior_dotnet_fullstack_developer(self):
        title = "Senior .NET Full-stack Developer"
        desc = "C# and ASP.NET Core web APIs with Blazor frontend for AI diagnostics."
        is_match, score, label = match_usama_cv(title, description=desc)
        assert not is_match
        assert score == 0
        assert "unrelated_stack" in label

    def test_rejects_dotnet_angular_agentic_ai_mismatch(self):
        title = "Senior Software Engineer (.NET, Angular & Agentic AI)"
        desc = "Core role in .NET 8 and Angular 17. Looking to add some agentic AI features."
        is_match, score, label = match_usama_cv(title, description=desc)
        # Rejected because .NET and Angular are unrelated primary stacks for a Python AI engineer
        assert not is_match
        assert score == 0


class TestPositiveUsamaCVSkills:
    """Verifies that jobs matching Muhammad Usama's 6+ years Senior AI Engineer profile match with high scores."""

    def test_matches_senior_ai_engineer(self):
        title = "Senior AI Engineer"
        desc = "Build scalable LLM and RAG pipelines using LangGraph, Python, and AWS Bedrock."
        is_match, score, label = match_usama_cv(title, description=desc)
        assert is_match
        assert score >= 95
        assert "Senior AI Engineer" in label

    def test_matches_generative_ai_engineer(self):
        title = "Generative AI Engineer"
        desc = "Fine-tune LLMs, build prompt engineering pipelines, and deploy using FastAPI and Docker."
        is_match, score, label = match_usama_cv(title, description=desc)
        assert is_match
        assert score >= 95
        assert "Generative AI" in label

    def test_matches_llm_rag_engineer(self):
        title = "LLM & RAG Specialist"
        desc = "Design multi-agent systems with vector databases (Pinecone, FAISS) and LangChain."
        is_match, score, label = match_usama_cv(title, description=desc)
        assert is_match
        assert score >= 95

    def test_matches_mlops_engineer(self):
        title = "MLOps Engineer"
        desc = "Deploy and scale model inference clusters on Kubernetes (EKS) with MLflow and CI/CD."
        is_match, score, label = match_usama_cv(title, description=desc)
        assert is_match
        assert score >= 90
        assert "MLOps" in label

    def test_matches_machine_learning_engineer(self):
        title = "Machine Learning Engineer"
        desc = "Develop deep learning models with PyTorch for production inference."
        is_match, score, label = match_usama_cv(title, description=desc)
        assert is_match
        assert score >= 90
        assert "Machine Learning" in label

    def test_matches_computer_vision_engineer(self):
        title = "Computer Vision Engineer"
        desc = "Train and deploy YOLO and Mask R-CNN object detection models."
        is_match, score, label = match_usama_cv(title, description=desc)
        assert is_match
        assert score >= 90
        assert "Computer Vision" in label

    def test_matches_data_scientist(self):
        title = "Data Scientist"
        desc = "Build predictive machine learning models and fraud detection pipelines."
        is_match, score, label = match_usama_cv(title, description=desc)
        assert is_match
        assert score >= 85


class TestModelGateIntegration:
    """Verifies that the main pipeline's ai_keyword_matches properly rejects non-AI roles."""

    def test_ai_keyword_matches_gate_with_sales_role(self):
        job = RawJob(
            source="linkedin",
            title="Account Executive - AI Software",
            company="SalesTech AI",
            url="https://example.com/job1",
            description="Sell enterprise AI solutions to Fortune 500.",
        )
        assert not ai_keyword_matches(job, ["AI", "Machine Learning"])

    def test_ai_keyword_matches_gate_with_valid_ai_role(self):
        job = RawJob(
            source="weworkremotely",
            title="Lead AI Engineer",
            company="AI Health",
            url="https://example.com/job2",
            description="Lead LLM application development using Python and PyTorch.",
        )
        assert ai_keyword_matches(job, ["AI", "Machine Learning"])
