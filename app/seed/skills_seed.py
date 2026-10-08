"""Infer the skills an opportunity teaches — the edges of the career graph.

We don't hand-label all 100+ rows. Instead we derive skills from each
opportunity's title + tags + category using three layers, most-specific first:

1. ``TITLE_OVERRIDES`` — curated, high-fidelity skill sets for flagship
   programs (e.g. Google Data Analytics -> SQL, Excel, Tableau, …).
2. ``PHRASE_SKILLS`` / ``TOKEN_SKILLS`` — keyword inference over the text.
3. ``CATEGORY_SKILLS`` — a per-category floor so every course graph-connects.

Scholarships don't *teach* skills, so they get none.
"""
from __future__ import annotations

import re

# Curated overrides keyed by a case-insensitive substring of the title. These
# add specifics (Tableau, Wireframing, …) that plain keywords would miss.
TITLE_OVERRIDES: dict[str, list[str]] = {
    "Google Data Analytics": ["Data Analysis", "SQL", "Spreadsheets", "Tableau", "R", "Data Cleaning", "Data Visualization"],
    "Google Advanced Data Analytics": ["Python", "Statistics", "Machine Learning", "Data Visualization", "Regression"],
    "Google UX Design": ["UX Design", "User Research", "Figma", "Prototyping", "Wireframing"],
    "Foundations of User Experience": ["UX Design", "User Research"],
    "Google Project Management": ["Project Management", "Agile", "Scrum", "Stakeholder Management"],
    "Google IT Support": ["IT Support", "Troubleshooting", "Networking", "Operating Systems", "System Administration"],
    "Google IT Automation with Python": ["Python", "Automation", "Git", "IT Support"],
    "Google Cybersecurity": ["Cybersecurity", "SIEM", "Linux", "Python", "Incident Response"],
    "IBM Data Science": ["Python", "SQL", "Data Science", "Machine Learning", "Data Visualization"],
    "IBM Data Analyst": ["Python", "SQL", "Excel", "Data Visualization", "Data Analysis"],
    "IBM Cybersecurity Analyst": ["Cybersecurity", "SIEM", "Incident Response", "Network Security"],
    "Machine Learning Specialization": ["Machine Learning", "Python", "Supervised Learning", "Neural Networks"],
    "Deep Learning Specialization": ["Deep Learning", "Neural Networks", "Python", "TensorFlow"],
    "Meta Front-End": ["React", "JavaScript", "HTML", "CSS", "Frontend Development"],
    "Meta Back-End": ["Python", "Django", "APIs", "Databases", "Backend Development"],
    "Power BI": ["Power BI", "Data Visualization", "DAX"],
    "Python for Everybody": ["Python", "Data Structures"],
    "CS50's Introduction to Programming with Python": ["Python", "Programming"],
    "CS50's Introduction to Artificial Intelligence": ["Artificial Intelligence", "Python", "Search Algorithms", "Machine Learning"],
    "CS50": ["Programming", "C", "Algorithms"],
    "Algorithms Specialization": ["Algorithms", "Data Structures"],
    "Java Programming": ["Java", "Object-Oriented Programming", "Data Structures"],
    "Web Design for Everybody": ["HTML", "CSS", "JavaScript", "Web Development"],
    "Front End Development Libraries": ["React", "Bootstrap", "Redux", "Frontend Development"],
    "Responsive Web Design": ["HTML", "CSS", "Responsive Design"],
    "JavaScript Algorithms": ["JavaScript", "Algorithms", "Data Structures"],
    "Excel Skills for Business": ["Excel", "Spreadsheets", "Data Analysis"],
    "Digital Marketing": ["Digital Marketing", "SEO", "Social Media Marketing", "Marketing Analytics"],
    "Successful Negotiation": ["Negotiation", "Communication"],
    "Financial Markets": ["Finance", "Investing"],
    "Entrepreneurship": ["Entrepreneurship", "Business Strategy"],
    "Business Foundations": ["Business", "Marketing", "Finance", "Operations"],
    "Azure Fundamentals": ["Microsoft Azure", "Cloud Computing"],
    "Azure Administrator": ["Microsoft Azure", "Cloud Administration"],
    "Azure Developer": ["Microsoft Azure", "Cloud Development"],
    "Azure AI Fundamentals": ["Artificial Intelligence", "Microsoft Azure", "Machine Learning"],
    "AWS Cloud Practitioner": ["AWS", "Cloud Computing"],
    "Solutions Architect": ["AWS", "Cloud Architecture"],
    "Architecting with Google Kubernetes": ["Kubernetes", "Google Cloud", "Containers"],
    "Terraform": ["Terraform", "Infrastructure as Code", "DevOps"],
    "Introduction to Kubernetes": ["Kubernetes", "Containers", "Docker"],
    "Security+": ["Cybersecurity", "Network Security", "Risk Management"],
    "Certified in Cybersecurity": ["Cybersecurity", "Network Security", "Access Control"],
    "Ethical Hacker": ["Ethical Hacking", "Penetration Testing", "Networking"],
    "Web Security Academy": ["Web Security", "Penetration Testing", "OWASP"],
    "CompTIA A+": ["IT Support", "Computer Hardware", "Operating Systems", "Troubleshooting"],
    "CompTIA Network+": ["Networking", "Network Security"],
    "CCNA": ["Networking", "Routing", "Switching"],
    "Networking Essentials": ["Networking", "TCP/IP"],
    "Bits and Bytes of Computer Networking": ["Networking", "TCP/IP"],
    "System Administration and IT Infrastructure": ["System Administration", "IT Support"],
    "Hardware and Operating Systems": ["Computer Hardware", "Operating Systems"],
    "Technical Support": ["IT Support", "Troubleshooting", "Help Desk"],
    "Elements of AI": ["Artificial Intelligence"],
    "AI For Everyone": ["Artificial Intelligence"],
    "Graphic Design": ["Graphic Design", "Typography", "Color Theory"],
    "Interaction Design": ["Interaction Design", "UX Design", "Prototyping"],
    "UI / UX Design": ["UI Design", "UX Design", "Prototyping"],
    "Visual Elements of User Interface": ["UI Design", "Visual Design"],
    "User Interface Design": ["UI Design"],
}

# Multiword / hyphenated matches (substring against the lowercased text).
PHRASE_SKILLS: dict[str, list[str]] = {
    "machine learning": ["Machine Learning"],
    "deep learning": ["Deep Learning", "Neural Networks"],
    "data science": ["Data Science", "Statistics"],
    "data analyt": ["Data Analysis", "Data Visualization"],
    "data analy": ["Data Analysis"],
    "power bi": ["Power BI", "Data Visualization"],
    "artificial intelligence": ["Artificial Intelligence"],
    "cloud comput": ["Cloud Computing"],
    "google cloud": ["Google Cloud", "Cloud Computing"],
    "web security": ["Web Security"],
    "web design": ["Web Development", "HTML", "CSS"],
    "web develop": ["Web Development"],
    "front end": ["Frontend Development", "HTML", "CSS"],
    "front-end": ["Frontend Development", "HTML", "CSS"],
    "back end": ["Backend Development", "APIs"],
    "back-end": ["Backend Development", "APIs"],
    "full stack": ["Full-Stack Development"],
    "full-stack": ["Full-Stack Development"],
    "computer science": ["Programming", "Computer Science"],
    "user experience": ["UX Design", "User Research"],
    "user interface": ["UI Design"],
    "interaction design": ["Interaction Design", "UX Design"],
    "graphic design": ["Graphic Design"],
    "project management": ["Project Management", "Planning"],
    "digital marketing": ["Digital Marketing", "Marketing"],
    "it support": ["IT Support", "Troubleshooting"],
    "technical support": ["IT Support", "Help Desk"],
    "help desk": ["Help Desk", "IT Support"],
    "operating system": ["Operating Systems"],
    "system administration": ["System Administration"],
    "ethical hack": ["Ethical Hacking", "Penetration Testing"],
}

# Single-word matches (exact token, so "ai" won't match "training").
TOKEN_SKILLS: dict[str, list[str]] = {
    "python": ["Python"], "sql": ["SQL"], "java": ["Java"],
    "javascript": ["JavaScript"], "react": ["React"], "html": ["HTML"], "css": ["CSS"],
    "kubernetes": ["Kubernetes", "Containers"], "terraform": ["Terraform"],
    "docker": ["Docker", "Containers"], "linux": ["Linux"], "git": ["Git"],
    "azure": ["Microsoft Azure", "Cloud Computing"], "aws": ["AWS", "Cloud Computing"],
    "gcp": ["Google Cloud", "Cloud Computing"], "figma": ["Figma"], "excel": ["Excel"],
    "ai": ["Artificial Intelligence"], "networking": ["Networking"],
    "cybersecurity": ["Cybersecurity"], "security": ["Cybersecurity"],
    "algorithms": ["Algorithms"], "marketing": ["Marketing"], "finance": ["Finance"],
    "ux": ["UX Design"], "ui": ["UI Design"], "design": ["Design"],
    "programming": ["Programming"], "agile": ["Agile", "Scrum"],
}

# Per-category floor so every course connects into the graph.
CATEGORY_SKILLS: dict[str, list[str]] = {
    "Cloud Computing": ["Cloud Computing"],
    "Data & AI": ["Data Analysis"],
    "Cybersecurity": ["Cybersecurity"],
    "Software Development": ["Programming"],
    "Design": ["Design"],
    "Business & PM": ["Business"],
    "IT Support": ["IT Support"],
    # Science & Health
    "Mathematics": ["Mathematics"],
    "Physics": ["Physics"],
    "Chemistry": ["Chemistry"],
    "Biology": ["Biology"],
    "Medicine": ["Medicine"],
    "Pharmacy": ["Pharmacology"],
    "Public Health": ["Public Health"],
    "Neuroscience": ["Neuroscience"],
    # Engineering
    "Mechanical Engineering": ["Mechanical Engineering"],
    "Electrical Engineering": ["Electrical Engineering"],
    "Civil Engineering": ["Civil Engineering"],
    "Industrial Engineering": ["Operations Management"],
    "Renewable Energy": ["Renewable Energy"],
    # Business & Social Sciences
    "Marketing": ["Marketing"],
    "Finance": ["Finance"],
    "Economics": ["Economics"],
    "Psychology": ["Psychology"],
    "Law": ["Law"],
    "Education": ["Teaching"],
}


def _dedupe(items: list[str]) -> list[str]:
    seen: dict[str, None] = {}
    for it in items:
        seen.setdefault(it, None)
    return list(seen)


def infer_skills(title: str, category: str, tags=None, kind: str = "course") -> list[str]:
    """Best-effort skills an opportunity teaches. Scholarships return none."""
    if kind == "scholarship":
        return []

    title = title or ""
    tags = tags or []
    # Match on title + tags only — NOT the category name, so e.g. the "Data & AI"
    # category doesn't stamp "Artificial Intelligence" onto a pure SQL course.
    text = f"{title} {' '.join(tags)}".lower()
    tokens = {t for t in re.split(r"[^a-z0-9+]+", text) if t}

    found: list[str] = []
    for sub, skills in TITLE_OVERRIDES.items():
        if sub.lower() in title.lower():
            found += skills
    for phrase, skills in PHRASE_SKILLS.items():
        if phrase in text:
            found += skills
    for tok, skills in TOKEN_SKILLS.items():
        if tok in tokens:
            found += skills

    found = _dedupe(found)
    if not found:  # sparse title/tags (e.g. job hubs) still get a category floor
        found = list(CATEGORY_SKILLS.get(category, []))
    return found


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
