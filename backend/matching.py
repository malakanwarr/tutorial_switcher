import uuid
from collections import defaultdict
from db import get_db_connection
from notify import send_match_emails

# --- 1. THE ALGORITHM ---

def build_partitions(students):
    """Groups students by Major, Semester, Batch, and Language (if sem <= 4)."""
    partitions = defaultdict(list)
    for s in students:
        if s["semester"] <= 4:
            key = (s["major"], s["semester"], s["batch"], s.get("english_level"), s.get("german_level"))
        else:
            key = (s["major"], s["semester"], s["batch"])
        partitions[key].append(s)
    return partitions

def build_graph(students):
    """Builds a directed graph of desired tutorials."""
    by_tutorial = defaultdict(list)
    for s in students:
        by_tutorial[s["current_tutorial"]].append(s["student_id"])

    graph = defaultdict(set)
    for s in students:
        for wanted_tutorial in s["desired_tutorials"]:
            for holder_id in by_tutorial.get(wanted_tutorial, []):
                if holder_id != s["student_id"]:
                    graph[s["student_id"]].add(holder_id)
    return graph

def find_cycles(graph):
    """Finds 2-way and 3-way cycles."""
    cycles = []
    seen = set()

    for start in graph:
        # 2-cycles
        for b in graph.get(start, ()):
            if start in graph.get(b, ()):
                key = frozenset((start, b))
                if key not in seen:
                    seen.add(key)
                    cycles.append((start, b))

        # 3-cycles
        for b in graph.get(start, ()):
            for c in graph.get(b, ()):
                if c in (start, b):
                    continue
                if start in graph.get(c, ()):
                    key = frozenset((start, b, c))
                    if key not in seen:
                        seen.add(key)
                        cycles.append((start, b, c))
    return cycles

def resolve_matches(students):
    """Runs the full pipeline and returns matched groups."""
    partitions = build_partitions(students)
    all_matches = []

    for _, group in partitions.items():
        graph = build_graph(group)
        cycles = find_cycles(graph)
        cycles.sort(key=len) # Prioritize 2-way over 3-way

        matched_ids = set()
        student_by_id = {s["student_id"]: s for s in group}

        for cycle in cycles:
            if any(sid in matched_ids for sid in cycle):
                continue

            n = len(cycle)
            slot_assignment = {}
            for i, sid in enumerate(cycle):
                next_student = student_by_id[cycle[(i + 1) % n]]
                slot_assignment[sid] = next_student["current_tutorial"]

            all_matches.append({
                "student_ids": list(cycle),
                "slot_assignment": slot_assignment,
            })
            matched_ids.update(cycle)

    return all_matches


# --- 2. THE DATABASE PIPELINE ---


def cleanup_ghost_matches(hours_to_wait=24):
    """Finds pending matches older than the time limit, dissolves them, and returns everyone to the pool."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # 1. Find match groups that are still pending after the time limit
        cursor.execute(f"""
            SELECT DISTINCT match_group_id 
            FROM matches 
            WHERE status = 'pending' 
            AND created_at < NOW() - INTERVAL '{hours_to_wait} hours'
        """)
        
        expired_groups = [row[0] for row in cursor.fetchall()]
        
        if expired_groups:
            for group_id in expired_groups:
                # 2. Mark the match as expired
                cursor.execute("UPDATE matches SET status = 'expired' WHERE match_group_id = %s", (group_id,))
                
                # 3. Return EVERYONE in this group safely back to the pool (no penalties)
                cursor.execute("""
                    UPDATE students 
                    SET is_matched = FALSE 
                    WHERE student_id IN (
                        SELECT student_id FROM matches WHERE match_group_id = %s
                    )
                """, (group_id,))
            
            conn.commit()
            print(f"🧹 Cleaned up {len(expired_groups)} ghosted matches and returned students to the pool.")
            
    except Exception as e:
        conn.rollback()
        print(f"Error during ghost cleanup: {e}")
    finally:
        cursor.close()
        conn.close()


def run_matching_engine():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Sweep for ghosts BEFORE looking for new matches
        cleanup_ghost_matches(hours_to_wait=3)
        
        # 1. Fetch all unmatched students WITH language levels
        cursor.execute("""
            SELECT student_id, university_email, whatsapp_number, major, semester, 
                   current_tutorial, english_level, german_level 
            FROM students WHERE is_matched = FALSE
        """)
        unmatched_rows = cursor.fetchall()
        
        if not unmatched_rows:
            print("No unmatched students in the pool.")
            return

        # 2. Fetch their desired slots IN ORDER OF PRIORITY
        students_data = []
        for row in unmatched_rows:
            student_id = row[0]
            # Notice the ORDER BY priority ASC here!
            cursor.execute("SELECT tutorial_id FROM desired_slots WHERE student_id = %s ORDER BY priority ASC", (student_id,))
            desired = [r[0] for r in cursor.fetchall()]
            
            students_data.append({
                "student_id": student_id,
                "email": row[1],
                "whatsapp": row[2],
                "major": row[3],
                "semester": row[4],
                "batch": student_id.split('-')[0], 
                "current_tutorial": row[5],
                "english_level": row[6],
                "german_level": row[7],
                "desired_tutorials": desired
            })

        # 3. Run the Algorithm
        matches = resolve_matches(students_data)
        if not matches:
            print("No matches found during this run.")
            return
            
        print(f"Found {len(matches)} successful match loops!")

        # 4. Process each match loop
        emails_to_send = []
        
        for match in matches:
            match_group_id = f"GROUP-{str(uuid.uuid4())[:8]}" # Unique ID for this specific trade
            cycle = match["student_ids"]
            cycle_length = len(cycle)
            
            for idx, sid in enumerate(cycle):
                # Find the student's full data
                student_info = next(s for s in students_data if s["student_id"] == sid)
                
                # THE GIVER: The person giving this student their desired tutorial (next in the cycle)
                giver_id = cycle[(idx + 1) % cycle_length]
                giver_info = next(s for s in students_data if s["student_id"] == giver_id)
                
                # THE TAKER: The person taking this student's current tutorial (previous in the cycle)
                taker_id = cycle[(idx - 1) % cycle_length]
                taker_info = next(s for s in students_data if s["student_id"] == taker_id)
                
                partner_slot = match["slot_assignment"][sid]
                personal_token = str(uuid.uuid4())
                
                # Save to database
                cursor.execute("""
                    INSERT INTO matches (match_group_id, student_id, token, status)
                    VALUES (%s, %s, %s, 'pending')
                """, (match_group_id, sid, personal_token))
                
                # Mark as matched so they aren't pulled again
                cursor.execute("UPDATE students SET is_matched = TRUE WHERE student_id = %s", (sid,))
                
                # Queue the email with the new dynamic data
                emails_to_send.append({
                    "student_email": student_info["email"],
                    "student_id": sid,
                    "cycle_length": cycle_length,
                    "giver_whatsapp": giver_info["whatsapp"],
                    "taker_whatsapp": taker_info["whatsapp"],
                    "my_slot": student_info["current_tutorial"],
                    "partner_slot": partner_slot,
                    "token": personal_token
                })
                
        conn.commit()
        print("Database updated. Firing email engine...")
        
        # 5. Send the notifications
        send_match_emails(emails_to_send)
        
    except Exception as e:
        conn.rollback()
        print(f"Error during matching run: {e}")
    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    print("Starting matching engine run...")
    run_matching_engine()