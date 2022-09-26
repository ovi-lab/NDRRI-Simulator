import pyttsx3
import time

LOCAL_RSVP_STREAM_FILE = None
LOCAL_STRING = None

# engine = pyttsx3.init()
def onWord(name, location, length):
    word = LOCAL_STRING[int(location) : int(location + length)]
    save_to_stream_file(word)

def onEnd(name, completed):
   save_to_stream_file("TTSOver")

def speak(RSVP_STREAM_FILE, string, WPM, adjustment, volume):
    # Setting the local stream file variable
    global LOCAL_RSVP_STREAM_FILE
    global LOCAL_STRING
    LOCAL_RSVP_STREAM_FILE = RSVP_STREAM_FILE
    LOCAL_STRING = string

    # Initializing the Text-To-Speech Engine
    engine = pyttsx3.init()

    # Twaeking the TTS properties
    engine.setProperty("rate", WPM - adjustment)
    engine.setProperty("volume", volume)

    voices = engine.getProperty("voices")
    engine.setProperty("voice", voices[0].id)

    # Listening for events
    engine.connect('started-word', onWord)
    engine.connect('finished-utterance', onEnd)

    # Loading and playing the text to engine
    engine.say(string, "TTS_prompt")
    engine.runAndWait()

def save_to_stream_file(word):
    try:
        file = open(LOCAL_RSVP_STREAM_FILE, "w")
        file.write(word)
        file.close()
    except Exception as e:
        print("Error writing the stream file\n", str(e))

if __name__ == "__main__":
    speak("test.txt", "This is a, sample text", 200)