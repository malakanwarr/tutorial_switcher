document.getElementById("swapform").addEventListener("submit", async function(event) {
    event.preventDefault(); // Stops the page from refreshing

    // 1. Grab all the values from the form
    const studentId = document.getElementById("student_id").value;
    const personalEmail = document.getElementById("personal_email").value;
    const whatsapp = document.getElementById("whatsapp_number").value;
    const major = document.getElementById("major").value;
    const semester = parseInt(document.getElementById("semester").value);
    const currentTutorial = parseInt(document.getElementById("current_tutorial").value);

    // 2. The Batch Year Magic Shortcut
    // If ID is "61-7627", this splits it at the dash and grabs "61"
    const batchYear = studentId.split("-")[0]; 

    // 3. Bundle the Preferences
    const desiredTutorials = [];
    const pref1 = document.getElementById("pref_1").value;
    const pref2 = document.getElementById("pref_2").value;
    const pref3 = document.getElementById("pref_3").value;

    if (pref1) desiredTutorials.push(parseInt(pref1));
    if (pref2) desiredTutorials.push(parseInt(pref2));
    if (pref3) desiredTutorials.push(parseInt(pref3));

    // 4. Create the final package (matches the Pydantic SwitchRequest perfectly)
    const requestData = {
        student_id: studentId,
        whatsapp_number: whatsapp,
        university_email: personalEmail, // Sending personal email to the DB column
        major: major,
        semester: semester,
        batch: batchYear,
        current_tutorial: currentTutorial,
        desired_tutorials: desiredTutorials,
        requires_lang_match: false // Hardcoded for now, can add checkboxes later if needed
    };

    // 5. Send it to the Waiter (FastAPI)
    try {
        const response = await fetch("http://127.0.0.1:8000/register", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify(requestData)
        });

        const result = await response.json();

        if (response.ok) {
            alert("Success! You are in the matching pool. We will email you when a match is found.");
            document.getElementById("swapform").reset(); // Clears the form
        } else {
            alert("Error: " + result.detail);
        }
    } catch (error) {
        alert("Cannot connect to the server. Make sure your Python backend is running!");
    }
});