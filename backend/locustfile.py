import random
import uuid
from locust import HttpUser, task, between

# Ripped exactly from your frontend HTML
GENERAL_GROUPS = [
    "Engineering (General)", "Management (General)", "Pharmacy and Biotechnology", 
    "Applied Sciences and Arts", "Dentistry", "Law and Legal Studies"
]

FACULTIES = [
    "Media Engineering and Technology (MET)", "Information Engineering and Technology (IET)", 
    "Engineering and Materials Science (EMS)", "Pharmacy and Biotechnology", 
    "Management Technology", "Applied Sciences and Arts", "Dentistry", "Law and Legal Studies"
]

SPECIFIC_MAJORS = [
    "Computer Science and Engineering (CSEN)", "Digital Media Engineering and Technology (DMET)",
    "Networks", "Communications", "Electronics",
    "Materials Engineering", "Design and Production Engineering", "Mechatronics Engineering", 
    "Civil Engineering", "Architecture Engineering",
    "PharmD", "Biotechnology", "PharmD-Clinical Pharmacy",
    "General Management", "Business Informatics (BI)", "Technology-based Management",
    "Graphic Design", "Media Design", "Product Design",
    "Dentistry", "Law and Legal Studies"
]

class GUCSwitcherLoadTest(HttpUser):
    wait_time = between(1, 3) 

    def on_start(self):
        self.student_id = f"61-{random.randint(10000, 99999)}"
        self.email = f"fake_{uuid.uuid4().hex[:6]}@student.guc.edu.eg"
        self.whatsapp = f"+2010{random.randint(10000000, 99999999)}"
        self.batch = "61"
        
        # --- HARDCODE EVERYONE INTO THE EXACT SAME BUCKET ---
        self.semester = 7
        self.major = "Computer Science and Engineering (CSEN)"
        self.requires_lang_match = False
        self.english_level = None
        self.german_level = None
        
        # (Keep the tutorials logic the exact same)
        all_tutorials = list(range(1, 35))
        self.current_tutorial = random.choice(all_tutorials)
        
        remaining_tutorials = [t for t in all_tutorials if t != self.current_tutorial]
        self.desired_tutorials = random.sample(remaining_tutorials, random.randint(1, 3))
        
        self.is_registered = False

    @task(3)
    def register_student(self):
        if not self.is_registered:
            payload = {
                "student_id": self.student_id,
                "whatsapp_number": self.whatsapp,
                "university_email": self.email,
                "major": self.major,
                "semester": self.semester,
                "batch": self.batch,
                "current_tutorial": self.current_tutorial,
                "desired_tutorials": self.desired_tutorials,
                "requires_lang_match": self.requires_lang_match,
                "english_level": self.english_level,
                "german_level": self.german_level
            }
            
            with self.client.post("/register", json=payload, catch_response=True) as response:
                if response.status_code == 200:
                    self.is_registered = True
                    response.success()
                else:
                    response.failure(f"Registration Failed: {response.text}")

    @task(1)
    def check_status(self):
        if self.is_registered:
            payload = {
                "student_id": self.student_id,
                "university_email": self.email
            }
            self.client.post("/status", json=payload)