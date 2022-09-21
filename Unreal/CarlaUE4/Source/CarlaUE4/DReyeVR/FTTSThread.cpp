// Copyright notice
#include "TTSThread.h" // Change this to reference the header file above
#include <cmath>

#pragma region Main Thread Code
// This code will be run on the thread that invoked this thread (i.e. game thread)

std::string* TextStdStringPtr;

FTTSThread::FTTSThread(std::string& TextStdString, int32 WPM)
{
	// Constructs the actual thread object. It will begin execution immediately
	// If you've passed in any inputs, set them up before calling this.
	this->WPM = WPM;
	TextStdStringPtr = &TextStdString;
	Thread = FRunnableThread::Create(this, TEXT("TTS Thread"));
}


FTTSThread::~FTTSThread()
{
	if (Thread)
	{
		// Kill() is a blocking call, it waits for the thread to finish.
		// Hopefully that doesn't take too long
		Thread->Kill();
		delete Thread;
    UE_LOG(LogTemp, Warning, TEXT("TTS Thread: Killed"));

	}
}


#pragma endregion
// The code below will run on the new thread.

uint32 FTTSThread::Run()
{
  UE_LOG(LogTemp, Warning, TEXT("TTS Thread: Running"));
  ISpVoice* pVoice = NULL;
  if (FAILED(::CoInitialize(NULL)))
  {
    return false;
  }
  HRESULT hr = CoCreateInstance(CLSID_SpVoice, NULL, CLSCTX_ALL, IID_ISpVoice, (void**)&pVoice);
  if (SUCCEEDED(hr))
  {
    /*This only works if all the characters are single byte, i.e. ASCII or ISO-8859-1.
    Anything multi-byte will fail miserably, including UTF-8. However, we only use ASCII in our case.*/
    std::wstring stemp = std::wstring((*TextStdStringPtr).begin(), (*TextStdStringPtr).end());
    LPCWSTR TextLString = stemp.c_str();
    pVoice->SetRate(ComputeAbsSpeed(WPM));
    hr = pVoice->Speak(TextLString, SPF_DEFAULT, NULL);
    pVoice->Release();
    pVoice = NULL;
  }
  ::CoUninitialize();
  UE_LOG(LogTemp, Warning, TEXT("TTS Thread: TTS task complete"));
  return TRUE;
}

int32 FTTSThread::ComputeAbsSpeed(int32 WPM)
{
      float TTSAbsSpeed = 0.f;
      if (WPM > TTS_DEFAULT_SPEED)
      {
          TTSAbsSpeed = log(WPM/TTS_DEFAULT_SPEED)*10/log(3);
      }
      else if (WPM < TTS_DEFAULT_SPEED)
      {
          TTSAbsSpeed = log(TTS_DEFAULT_SPEED/WPM)*10/log(3);
      }
      /* Adjusting WPM based on reading task speed. */
      TTSAbsSpeed *= TTS_WPM_ADJUST;
      /* Ensuring that the AbsSpeed in [-10, 10] */
      TTSAbsSpeed = (TTSAbsSpeed > 10.f) ? 10.f : TTSAbsSpeed;
      TTSAbsSpeed = (TTSAbsSpeed < -10.f) ? -10.f : TTSAbsSpeed;

      UE_LOG(LogTemp, Display, TEXT("AbsSpeed: %d"), round(TTSAbsSpeed));
      return round(TTSAbsSpeed);
}