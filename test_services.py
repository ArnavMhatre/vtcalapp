from main import preprocess_image, extract_text_from_image, parse_timetable_text

# Test OCR logic
with open("Sample_Img.png", "rb") as f:
    img_bytes = f.read()
image = preprocess_image(img_bytes)
text = extract_text_from_image(image)
# print("Extracted text:\n", text)

# Test parser logic
events = parse_timetable_text(text)
for i in range(len(events)):
    print(i, "th event:", events[i])


'''from pyvt import Timetable


vt = Timetable()
course = vt.crn_lookup('83538', open_only=False)
print(course)
print(course.location)'''