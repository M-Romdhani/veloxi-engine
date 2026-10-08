from app.pipeline.classify import classify, infer_kind


def test_known_titles_map_to_categories():
    assert classify("Google Cybersecurity Professional Certificate").category == "Cybersecurity"
    assert classify("AWS Cloud Practitioner Essentials").category == "Cloud Computing"
    assert classify("Machine Learning Specialization").category == "Data & AI"
    assert classify("CS50: Introduction to Computer Science").category == "Software Development"
    assert classify("Google UX Design Professional Certificate").category == "Design"
    assert classify("Google Project Management Professional Certificate").category == "Business & PM"
    assert classify("Google IT Support Professional Certificate").category == "IT Support"


def test_difficulty_signals():
    assert classify("Introduction to Python for Beginners").difficulty == "Beginner"
    assert classify("Advanced Kubernetes Deep Dive").difficulty == "Advanced"


def test_unknown_falls_back_to_default():
    result = classify("Qwerty zxcv asdf")
    assert result.category == "Software Development"
    assert result.confidence == 0.0
    assert result.method == "heuristic"


def test_infer_kind():
    assert infer_kind("Chevening Scholarships (fully funded master's)") == "scholarship"
    assert infer_kind("Senior Backend Engineer (Remote) — hiring now") == "job"
    assert infer_kind("Google Data Analytics Professional Certificate") == "course"
