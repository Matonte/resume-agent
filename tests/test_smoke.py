from app.services.classifier import classify_job
from app.services.resume_tailor import generate_resume_draft

def test_classify_fintech():
    result = classify_job("Build financial transaction systems with auditability and compliance requirements.")
    assert result.archetype_id == "B_fintech_transaction_systems"

def test_generate_resume_draft():
    result = generate_resume_draft("Backend role focused on event-driven systems and observability.", "D_distributed_systems")
    assert result["summary"]
    assert result["selected_bullets"]
