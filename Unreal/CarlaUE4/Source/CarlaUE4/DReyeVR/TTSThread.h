#pragma once

#include "CoreMinimal.h"
#include "HAL/Runnable.h"
#include "sapi.h" /* Text to Speech using Microsoft SAPI 5.3 */
#include <string>
/**
 *
 */
class /*GAMENAME_API*/ FTTSThread : public FRunnable
{
public:

	// Constructor, create the thread by calling this
	FTTSThread(std::string& TextStdString, int32 WPM);

	// Destructor
	virtual ~FTTSThread() override;


	// Overriden from FRunnable
	// Do not call these functions youself, that will happen automatically
	uint32 Run() override; // Main data processing happens here

private:
	const float TTS_DEFAULT_SPEED = 163.f;
	const float TTS_WPM_ADJUST = 0.8f;
	int32 WPM;
	// Thread handle. Control the thread using this, with operators like Kill and Suspend
	FRunnableThread* Thread;
	
	// Helper methods
	int32 ComputeAbsSpeed(int32 WPM);
};