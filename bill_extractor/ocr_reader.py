from doctr.io import DocumentFile
from doctr.models import ocr_predictor

model = ocr_predictor(pretrained=True)


def readimage(image):
    doc = DocumentFile.from_images(image)
    result = model(doc)
    return result.export()


def readimages(*images):
    doc = DocumentFile.from_images(*images)
    result = model(doc)
    return result.export()


def extract_words(result_json):
    words = []
    for page in result_json["pages"]:
        for block in page["blocks"]:
            for line in block["lines"]:
                for word in line["words"]:
                    (x1, y1), (x2, y2) = word["geometry"]
                    words.append(
                        {
                            "text": word["value"],
                            "x": (x1 + x2) / 2,
                            "y": (y1 + y2) / 2,
                            "x_min": x1,
                        }
                    )
    return words


def cluster_lines(words, y_threshold=0.015):
    # sort top→bottom then left→right
    words = sorted(words, key=lambda w: (w["y"], w["x"]))
    lines = []
    current_line = []
    current_y = None
    for word in words:
        if current_y is None:
            current_y = word["y"]
            current_line.append(word)
            continue
        if abs(word["y"] - current_y) < y_threshold:
            current_line.append(word)
        else:
            lines.append(current_line)
            current_line = [word]
            current_y = word["y"]
    if current_line:
        lines.append(current_line)
    # sort words left→right
    for line in lines:
        line.sort(key=lambda w: w["x_min"])
    return lines


def getlines(lines):
    texts = []
    for line in lines:
        text = " ".join(w["text"] for w in line)
        texts.append(text)
    return texts


def process(image):
    data = readimage(image)
    words = extract_words(data)
    lines = cluster_lines(words)
    text = getlines(lines)
    return text


if __name__ == "__main__":
    image = "food_04.jpeg"
    text = process(image)
    from pprint import pprint

    pprint(text)
