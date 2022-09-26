import random

def main():
    # TOR Scenarios
    TORS = ["EW", "LVAD", "CSA", "ACR"]
    # Text Presentation Techniques
    TPT = ["STP", "RSVP"]
    # Audio Assistance
    A = ["NAA", "AA"]
    # Comprehension texts
    CT = ["TextFile1.txt", "TextFile2.txt", "TextFile3.txt", "TextFile4.txt", "TextFile5.txt", "TextFile6.txt", "TextFile7.txt", "TextFile8.txt", ]
    # Shuffling the arrays
    random.shuffle(TORS)
    random.shuffle(TPT)
    random.shuffle(A)
    random.shuffle(CT)

    trial_no = 1
    string = "Pre-study questionnaire\n"
    for a in A:
        for tpt in TPT:
            for i in range(0, 2):
                string += "Trial No:" + str(trial_no) + ", Audio assistance:" + a +  ", Text Presentation Technique:" + tpt + ", TOR Scenario:" + TORS[(trial_no-1) % 4] + ", Text File:" + CT[trial_no - 1]
                string += "\nComprehension Test\n"
                trial_no += 1
            string += "NASA-TLX\nUEQ\n"
        random.shuffle(TORS)
        random.shuffle(TPT)
    file = open("procedure.txt", "w")
    file.write(string)
    file.close()
if __name__ == "__main__":
    main()