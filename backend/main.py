from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from db import get_db_connection  
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all websites to talk to it (perfect for local testing)
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods (POST, GET, etc.)
    allow_headers=["*"],  # Allows all headers
)

# ==========================================
# PYDANTIC MODELS (Data Validation)
# ==========================================

class SwitchRequest(BaseModel):
    student_id: str
    whatsapp_number: str
    university_email: str
    major: str
    semester: int
    batch: str
    current_tutorial: int
    desired_tutorials: List[int]
    requires_lang_match: bool = False
    english_level: Optional[str] = None
    german_level: Optional[str] = None

class StatusRequest(BaseModel):
    student_id: str
    university_email: str

class PreferenceUpdate(BaseModel):
    student_id: str
    university_email: str
    desired_tutorials: List[int]

class UpdateContactRequest(BaseModel):
    student_id: str
    current_email: str
    new_email: Optional[str] = None
    new_whatsapp: Optional[str] = None


# ==========================================
# ENDPOINTS
# ==========================================

@app.post("/register")
def register_student(request: SwitchRequest):
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # 1. THE BOUNCER: Check for duplicates before doing anything else
        cursor.execute("""
            SELECT student_id, university_email, whatsapp_number 
            FROM students 
            WHERE student_id = %s OR university_email = %s OR whatsapp_number = %s
        """, (request.student_id, request.university_email, request.whatsapp_number))
        
        existing_student = cursor.fetchone()

        if existing_student:
            db_id, db_email, db_phone = existing_student
            if db_id == request.student_id:
                raise ValueError("This Student ID is already registered! Use the Status page to update your preferences.")
            if db_email.lower() == request.university_email.lower():
                raise ValueError("This email is already in use by another student.")
            if db_phone == request.whatsapp_number:
                raise ValueError("This WhatsApp number is already registered.")

        # 2. THE INSERT: Now a strict, standard insert without the UPSERT backdoor
        cursor.execute("""
            INSERT INTO students (
                student_id, whatsapp_number, university_email, major, 
                semester, batch, current_tutorial, requires_lang_match, 
                english_level, german_level
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            request.student_id, request.whatsapp_number, request.university_email, 
            request.major, request.semester, request.batch, request.current_tutorial, 
            request.requires_lang_match, request.english_level, request.german_level
        ))

        # 3. Delete any old desired slots (just a safety precaution)
        cursor.execute("DELETE FROM desired_slots WHERE student_id = %s", (request.student_id,))

        # 4. Enumerate and save choices
        for priority_index, target_tutorial in enumerate(request.desired_tutorials):
            cursor.execute("""
                INSERT INTO desired_slots (student_id, tutorial_id, priority)
                VALUES (%s, %s, %s)
            """, (request.student_id, target_tutorial, priority_index + 1)) 

        conn.commit()
        return {"status": "success", "message": f"Student {request.student_id} successfully saved!"}

    except Exception as e:
        conn.rollback()
        # This catches our ValueError and sends it safely to the frontend!
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        cursor.close()
        conn.close()


@app.post("/status")
def get_status(request: StatusRequest):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT university_email, major, semester, batch,
                   requires_lang_match, english_level, german_level,
                   current_tutorial, is_matched
            FROM students
            WHERE student_id = %s
        """, (request.student_id,))
        row = cursor.fetchone()

        # Validate Identity
        if not row or row[0].lower() != request.university_email.strip().lower():
            raise HTTPException(status_code=404, detail="We couldn't find a registration matching that Student ID and email.")

        (email, major, semester, batch, requires_lang_match,
         english_level, german_level, current_tutorial, is_matched) = row

        if is_matched:
            return {
                "in_pool": False,
                "message": "You've already been matched! Check your email for the swap details."
            }

        # Apply Wall Garden Rules
        base_filter = "s.major = %s AND s.semester = %s AND s.batch = %s AND s.student_id != %s AND s.is_matched = FALSE"
        params = [major, semester, batch, request.student_id]

        if semester <= 4:
            base_filter += " AND s.english_level = %s AND s.german_level = %s"
            params += [english_level, german_level]

        # How many eligible students want my slot?
        cursor.execute(f"""
            SELECT COUNT(DISTINCT s.student_id)
            FROM students s
            JOIN desired_slots d ON d.student_id = s.student_id
            WHERE {base_filter} AND d.tutorial_id = %s
        """, params + [current_tutorial])
        students_wanting_your_slot = cursor.fetchone()[0]

        # Breakdown of demand for EACH of my preferences
        cursor.execute("SELECT tutorial_id FROM desired_slots WHERE student_id = %s ORDER BY priority ASC", (request.student_id,))
        my_desired = [r[0] for r in cursor.fetchall()]

        preference_breakdown = []
        total_preferences_available = 0
        
        for pref in my_desired:
            cursor.execute(f"""
                SELECT COUNT(DISTINCT s.student_id)
                FROM students s
                JOIN desired_slots d ON d.student_id = s.student_id
                WHERE {base_filter} AND s.current_tutorial = %s AND d.tutorial_id = %s
            """, params + [pref, current_tutorial])
            
            demand_count = cursor.fetchone()[0]
            preference_breakdown.append({"tutorial": pref, "demand": demand_count})
            total_preferences_available += demand_count

        return {
            "in_pool": True,
            "students_wanting_your_slot": students_wanting_your_slot,
            "breakdown": preference_breakdown, # We send the breakdown list to the frontend
            "message": f"You're in the pool! We are actively searching for a match. Keep an eye on your email."
        }

    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail="Something went wrong checking your status. Please try again.")
    finally:
        cursor.close()
        conn.close()


@app.post("/update-preferences")
def update_preferences(request: PreferenceUpdate):
    if not request.desired_tutorials:
        raise HTTPException(status_code=400, detail="You must provide at least one preference.")

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Check if they exist and verify email
        cursor.execute(
            "SELECT university_email, is_matched FROM students WHERE student_id = %s",
            (request.student_id,)
        )
        row = cursor.fetchone()

        if not row or row[0].lower() != request.university_email.strip().lower():
            raise HTTPException(status_code=404, detail="We couldn't find a registration matching that Student ID and email.")

        if row[1]:
            raise HTTPException(
                status_code=409,
                detail="You're currently matched — check your email to confirm or report a flake before changing preferences."
            )

        # Clear old preferences and insert the new ones
        cursor.execute("DELETE FROM desired_slots WHERE student_id = %s", (request.student_id,))
        for priority_index, tutorial_id in enumerate(request.desired_tutorials):
            cursor.execute("""
                INSERT INTO desired_slots (student_id, tutorial_id, priority)
                VALUES (%s, %s, %s)
            """, (request.student_id, tutorial_id, priority_index + 1))

        conn.commit()
        return {"status": "success", "message": "Your preferences have been updated."}

    except HTTPException:
        raise
    except Exception:
        conn.rollback()
        raise HTTPException(status_code=400, detail="Update failed. Please check your inputs and try again.")
    finally:
        cursor.close()
        conn.close()

@app.put("/update-contact")
def update_contact(req: UpdateContactRequest):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # 1. Verify the student exists and the current email matches (Security check)
        cur.execute("SELECT id FROM students WHERE student_id = %s AND university_email = %s", 
                    (req.student_id, req.current_email))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Student not found or incorrect current email.")

        # 2. Build the update query dynamically based on what they provided
        updates = []
        params = []
        
        if req.new_email:
            updates.append("university_email = %s")
            params.append(req.new_email)
        if req.new_whatsapp:
            updates.append("whatsapp_number = %s")
            params.append(req.new_whatsapp)

        if not updates:
            raise HTTPException(status_code=400, detail="No new contact info provided.")

        params.append(req.student_id)
        
        # 3. Execute update
        query = f"UPDATE students SET {', '.join(updates)} WHERE student_id = %s"
        cur.execute(query, tuple(params))
        conn.commit()

        return {"message": "Contact information updated successfully!"}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cur.close()
        conn.close()


# ==========================================
# UI RENDERING ENDPOINTS
# ==========================================

# Reusable HTML template wrapper for clean UI pages
def render_status_page(title, message, is_success=True):
    accent_color = "#4ade80" if is_success else "#f87171"
    icon = "🎉" if is_success else "⚠️"
    
    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{title}</title>
        <style>
            body {{
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 100%);
                color: #f8fafc;
                margin: 0;
                display: flex;
                justify-content: center;
                align-items: center;
                height: 100vh;
            }}
            .card {{
                background: rgba(30, 41, 59, 0.85);
                backdrop-filter: blur(12px);
                border: 1px solid rgba(255, 255, 255, 0.1);
                padding: 40px;
                border-radius: 20px;
                text-align: center;
                max-width: 450px;
                box-shadow: 0 20px 40px rgba(0, 0, 0, 0.5);
            }}
            .icon {{ font-size: 3rem; margin-bottom: 15px; }}
            h1 {{ color: {accent_color}; font-size: 1.8rem; margin-bottom: 15px; }}
            p {{ color: #94a3b8; line-height: 1.6; font-size: 1.05rem; }}
        </style>
    </head>
    <body>
        <div class="card">
            <div class="icon">{icon}</div>
            <h1>{title}</h1>
            <p>{message}</p>
        </div>
    </body>
    </html>
    """

@app.get("/confirm-swap", response_class=HTMLResponse)
def confirm_swap(token: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT match_group_id, student_id FROM matches WHERE token = %s", (token,))
        match = cursor.fetchone()
        
        if not match:
            return render_status_page("Invalid Link", "This link is invalid or has already been used.", is_success=False)
            
        match_group_id = match[0]
        cursor.execute("UPDATE matches SET status = 'confirmed' WHERE token = %s", (token,))
        
        cursor.execute("SELECT status FROM matches WHERE match_group_id = %s", (match_group_id,))
        all_statuses = [row[0] for row in cursor.fetchall()]
        conn.commit()

        if all(status == 'confirmed' for status in all_statuses):
            return render_status_page("Swap Complete! 🚀", "Everyone has confirmed! Your tutorial swap is officially locked in. Good luck with classes!")
        else:
            return render_status_page("Confirmation Received 👍", "You've successfully confirmed! We are just waiting for your partner(s) to click confirm as well.")
        
    except Exception as e:
        conn.rollback()
        return render_status_page("Server Error", str(e), is_success=False)
    finally:
        cursor.close()
        conn.close()


@app.get("/flake-swap", response_class=HTMLResponse)
def flake_swap(token: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # 1. Find the group ID associated with this token
        cursor.execute("SELECT match_group_id FROM matches WHERE token = %s", (token,))
        match = cursor.fetchone()
        
        if not match:
            return render_status_page("Invalid Link", "This link is invalid or the match has already been cancelled.", is_success=False)
            
        match_group_id = match[0]
        
        # 2. Mark the ENTIRE group's match as 'cancelled' (This triggers the Blacklist!)
        cursor.execute("UPDATE matches SET status = 'cancelled' WHERE match_group_id = %s", (match_group_id,))
        
        # 3. Free EVERYONE in that group back into the pool instantly (No exclusions!)
        cursor.execute("""
            UPDATE students 
            SET is_matched = FALSE 
            WHERE student_id IN (
                SELECT student_id FROM matches WHERE match_group_id = %s
            )
        """, (match_group_id,))
        
        conn.commit()
        return render_status_page(
            "Swap Cancelled 🛑", 
            "You have cancelled this match. Everyone involved has been safely returned to the active matching pool, and the system will not attempt to pair you with this group again.", 
            is_success=False
        )
        
    except Exception as e:
        conn.rollback()
        return render_status_page("Server Error", str(e), is_success=False)
    finally:
        cursor.close()
        conn.close()