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

def build_graph(students, blacklisted_pairs):
    """Builds a directed graph of desired tutorials, STRICTLY maintaining priority order and ignoring blacklists."""
    by_tutorial = defaultdict(list)
    for s in students:
        by_tutorial[s["current_tutorial"]].append(s["student_id"])

    graph = defaultdict(list)
    for s in students:
        seen_holders = set()
        for wanted_tutorial in s["desired_tutorials"]:
            for holder_id in by_tutorial.get(wanted_tutorial, []):
                if holder_id != s["student_id"] and holder_id not in seen_holders:

                    # --- SHIELD: Ignore previously failed pairings ---
                    if frozenset([s["student_id"], holder_id]) in blacklisted_pairs:
                        continue

                    graph[s["student_id"]].append(holder_id)
                    seen_holders.add(holder_id)
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

def get_cycle_score(cycle, student_by_id):
    """Calculates the 'happiness' score of a cycle based on preferences. Lower is better."""
    score = 0
    n = len(cycle)
    for i, sid in enumerate(cycle):
        student = student_by_id[sid]
        target_tutorial = student_by_id[cycle[(i + 1) % n]]["current_tutorial"]
        try:
            score += student["desired_tutorials"].index(target_tutorial)
        except ValueError:
            score += 99
    return score

def resolve_matches(students, blacklisted_pairs):
    """Runs the full pipeline and returns matched groups."""
    partitions = build_partitions(students)
    all_matches = []

    for _, group in partitions.items():
        graph = build_graph(group, blacklisted_pairs)
        cycles = find_cycles(graph)

        student_by_id = {s["student_id"]: s for s in group}

        # 1st priority: shortest length (2-way over 3-way)
        # 2nd priority: lowest preference score (1st choices beat 3rd choices)
        cycles.sort(key=lambda c: (len(c), get_cycle_score(c, student_by_id)))

        matched_ids = set()

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
        cursor.execute(f"""
            SELECT DISTINCT match_group_id 
            FROM matches 
            WHERE status = 'pending' 
            AND created_at < NOW() - INTERVAL '{hours_to_wait} hours'
        """)

        expired_groups = [row[0] for row in cursor.fetchall()]

        if expired_groups:
            for group_id in expired_groups:
                cursor.execute("UPDATE matches SET status = 'expired' WHERE match_group_id = %s", (group_id,))
                cursor.execute("""
                    UPDATE students 
                    SET is_matched = FALSE 
                    WHERE student_id IN (
                        SELECT student_id FROM matches WHERE match_group_id = %s
                    )
                """, (group_id,))

            conn.commit()
            print(f"Cleaned up {len(expired_groups)} ghosted matches and returned students to the pool.")

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
        # FIX 1: restored to 24 hours — students get a full day before a
        # match dissolves, instead of 3 hours.
        cleanup_ghost_matches(hours_to_wait=24)

        # FIX 2: 'expired' added alongside 'cancelled'. Without this, a
        # match that dissolves from timeout (not an explicit flake click)
        # was never blacklisted, so the same two students could be
        # instantly re-matched with each other in the very next run —
        # this was the actual cause of the repeated identical emails.
        cursor.execute("""
            SELECT m1.student_id, m2.student_id
            FROM matches m1
            JOIN matches m2 ON m1.match_group_id = m2.match_group_id
            WHERE m1.status IN ('cancelled', 'expired') AND m1.student_id != m2.student_id
        """)
        blacklisted_pairs = {frozenset([row[0], row[1]]) for row in cursor.fetchall()}

        cursor.execute("""
            SELECT student_id, university_email, whatsapp_number, major, semester, 
            current_tutorial, english_level, german_level, batch 
            FROM students WHERE is_matched = FALSE
            ORDER BY created_at ASC
        """)
        unmatched_rows = cursor.fetchall()

        if not unmatched_rows:
            print("No unmatched students in the pool.")
            return

        students_data = []
        for row in unmatched_rows:
            student_id = row[0]
            cursor.execute("SELECT tutorial_id FROM desired_slots WHERE student_id = %s ORDER BY priority ASC", (student_id,))
            desired = [r[0] for r in cursor.fetchall()]

            students_data.append({
                "student_id": student_id,
                "email": row[1],
                "whatsapp": row[2],
                "major": row[3],
                "semester": row[4],
                "batch": row[8],
                "current_tutorial": row[5],
                "english_level": row[6],
                "german_level": row[7],
                "desired_tutorials": desired
            })

        matches = resolve_matches(students_data, blacklisted_pairs)
        if not matches:
            print("No matches found during this run.")
            return

        print(f"Found {len(matches)} successful match loops!")

        emails_to_send = []

        for match in matches:
            match_group_id = f"GROUP-{str(uuid.uuid4())[:8]}"
            cycle = match["student_ids"]
            cycle_length = len(cycle)

            for idx, sid in enumerate(cycle):
                student_info = next(s for s in students_data if s["student_id"] == sid)
                partner_slot = match["slot_assignment"][sid]
                personal_token = str(uuid.uuid4())

                cursor.execute("""
                    INSERT INTO matches (match_group_id, student_id, token, status)
                    VALUES (%s, %s, %s, 'pending')
                """, (match_group_id, sid, personal_token))

                cursor.execute("UPDATE students SET is_matched = TRUE WHERE student_id = %s", (sid,))

                if cycle_length == 2:
                    partner_id = cycle[(idx + 1) % 2]
                    partner_info = next(s for s in students_data if s["student_id"] == partner_id)
                    emails_to_send.append({
                        "student_email": student_info["email"],
                        "student_id": sid,
                        "swap_type": "standard",
                        "partner_whatsapp": partner_info["whatsapp"],
                        "my_slot": student_info["current_tutorial"],
                        "partner_slot": partner_slot,
                        "token": personal_token
                    })

                elif cycle_length == 3:
                    if idx == 0:
                        step1_id = cycle[2]
                        step2_id = cycle[1]
                        step1_info = next(s for s in students_data if s["student_id"] == step1_id)
                        step2_info = next(s for s in students_data if s["student_id"] == step2_id)

                        emails_to_send.append({
                            "student_email": student_info["email"],
                            "student_id": sid,
                            "swap_type": "double-switch",
                            "step1_whatsapp": step1_info["whatsapp"],
                            "step2_whatsapp": step2_info["whatsapp"],
                            "step1_slot": step1_info["current_tutorial"],
                            "my_slot": student_info["current_tutorial"],
                            "partner_slot": partner_slot,
                            "token": personal_token
                        })
                    else:
                        pivot_id = cycle[0]
                        pivot_info = next(s for s in students_data if s["student_id"] == pivot_id)

                        emails_to_send.append({
                            "student_email": student_info["email"],
                            "student_id": sid,
                            "swap_type": "standard",
                            "partner_whatsapp": pivot_info["whatsapp"],
                            "my_slot": student_info["current_tutorial"],
                            "partner_slot": partner_slot,
                            "token": personal_token
                        })

        conn.commit()
        print("Database updated. Firing email engine...")

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