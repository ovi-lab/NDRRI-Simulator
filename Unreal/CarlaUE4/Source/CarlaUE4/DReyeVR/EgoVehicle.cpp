#include "EgoVehicle.h"
#include "Carla/Actor/ActorAttribute.h"             // FActorAttribute
#include "Carla/Actor/ActorRegistry.h"              // Register
#include "Carla/Game/CarlaStatics.h"                // GetEpisode
#include "Carla/Vehicle/CarlaWheeledVehicleState.h" // ECarlaWheeledVehicleState
#include "DReyeVRPawn.h"                            // ADReyeVRPawn
#include "DrawDebugHelpers.h"                       // Debug Line/Sphere
#include "Engine/EngineTypes.h"                     // EBlendMode
#include "Engine/World.h"                           // GetWorld
#include "GameFramework/Actor.h"                    // Destroy
#include "Kismet/KismetSystemLibrary.h"             // PrintString, QuitGame
#include "Math/Rotator.h"                           // RotateVector, Clamp
#include "Math/UnrealMathUtility.h"                 // Clamp
#include "Kismet/KismetStringLibrary.h"             // GetSubString
#include <algorithm>
#include "TTSThread.h"                              // Text to Speech Thread
#include <math.h>                                   // Natural log
#include "HAL/FileManager.h"
#include <string>

// Sets default values
AEgoVehicle::AEgoVehicle(const FObjectInitializer& ObjectInitializer) : Super(ObjectInitializer)
{
	ReadConfigVariables();

	// this actor ticks AFTER the physics simulation is done
	PrimaryActorTick.bCanEverTick = true;
	PrimaryActorTick.TickGroup = TG_PostPhysics;

	// Set up the root position to be the this mesh
	SetRootComponent(GetMesh());

	// Initialize the camera components
	ConstructCameraRoot();

	// Initialize audio components
	ConstructEgoSounds();

	// Initialize mirrors
	ConstructMirrors();

	// Reset the Signal File to an invalid/Illogical communication
	WriteSignalFile(TEXT("5"));

	// Reset the RSVP Stream file
	ResetTTSStreamFile();

	// Reading Settings file to determine the behavior of the Heads-Up Display
	ReadSettingsFile();

	// Retrive text from local files to display on HUD
	RetriveText();

	// Initialize text render components
	ConstructDashText();

	// Initialize the steering wheel
	ConstructSteeringWheel();
}

void AEgoVehicle::ReadConfigVariables()
{
	ReadConfigValue("EgoVehicle", "CameraInit", CameraLocnInVehicle);
	ReadConfigValue("EgoVehicle", "DashLocation", DashboardLocnInVehicle);
	ReadConfigValue("EgoVehicle", "SpeedometerInMPH", bUseMPH);
	ReadConfigValue("EgoVehicle", "EnableTurnSignalAction", bEnableTurnSignalAction);
	ReadConfigValue("EgoVehicle", "TurnSignalDuration", TurnSignalDuration);
	// mirrors
	auto InitMirrorParams = [](const FString& Name, struct MirrorParams& Params)
	{
		Params.Name = Name;
		ReadConfigValue("Mirrors", Params.Name + "MirrorEnabled", Params.Enabled);
		ReadConfigValue("Mirrors", Params.Name + "MirrorPos", Params.MirrorPos);
		ReadConfigValue("Mirrors", Params.Name + "MirrorRot", Params.MirrorRot);
		ReadConfigValue("Mirrors", Params.Name + "MirrorScale", Params.MirrorScale);
		ReadConfigValue("Mirrors", Params.Name + "ReflectionPos", Params.ReflectionPos);
		ReadConfigValue("Mirrors", Params.Name + "ReflectionRot", Params.ReflectionRot);
		ReadConfigValue("Mirrors", Params.Name + "ReflectionScale", Params.ReflectionScale);
		ReadConfigValue("Mirrors", Params.Name + "ScreenPercentage", Params.ScreenPercentage);
	};
	InitMirrorParams("Rear", RearMirrorParams);
	InitMirrorParams("Left", LeftMirrorParams);
	InitMirrorParams("Right", RightMirrorParams);
	// rear mirror chassis
	ReadConfigValue("Mirrors", "RearMirrorChassisPos", RearMirrorChassisPos);
	ReadConfigValue("Mirrors", "RearMirrorChassisRot", RearMirrorChassisRot);
	ReadConfigValue("Mirrors", "RearMirrorChassisScale", RearMirrorChassisScale);
	// steering wheel
	ReadConfigValue("SteeringWheel", "InitLocation", InitWheelLocation);
	ReadConfigValue("SteeringWheel", "InitRotation", InitWheelRotation);
	ReadConfigValue("SteeringWheel", "MaxSteerAngleDeg", MaxSteerAngleDeg);
	ReadConfigValue("SteeringWheel", "MaxSteerVelocity", MaxSteerVelocity);
	ReadConfigValue("SteeringWheel", "SteeringScale", SteeringAnimScale);
	// other/cosmetic
	ReadConfigValue("EgoVehicle", "ActorRegistryID", EgoVehicleID);
	ReadConfigValue("EgoVehicle", "DrawDebugEditor", bDrawDebugEditor);
	// inputs
	ReadConfigValue("VehicleInputs", "ScaleSteeringDamping", ScaleSteeringInput);
	ReadConfigValue("VehicleInputs", "ScaleThrottleInput", ScaleThrottleInput);
	ReadConfigValue("VehicleInputs", "ScaleBrakeInput", ScaleBrakeInput);
}

void AEgoVehicle::BeginPlay()
{
	// Called when the game starts or when spawned
	Super::BeginPlay();

	// Get information about the world
	World = GetWorld();
	Episode = UCarlaStatics::GetCurrentEpisode(World);

	// Spawn and attach the EgoSensor
	InitSensor();

	// initialize
	InitAIPlayer();

	// Bug-workaround for initial delay on throttle; see https://github.com/carla-simulator/carla/issues/1640
	this->GetVehicleMovementComponent()->SetTargetGear(1, true);

	// Register Ego Vehicle with ActorRegistry
	Register();

	UE_LOG(LogTemp, Log, TEXT("Initialized DReyeVR EgoVehicle"));
}

void AEgoVehicle::BeginDestroy()
{
	Super::BeginDestroy();

	// destroy all spawned entities
	if (EgoSensor)
		EgoSensor->Destroy();
}

// Called every frame
void AEgoVehicle::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);

	// Update the positions based off replay data
	ReplayTick();

	// Get the current data from the AEgoSensor and use it
	UpdateSensor(DeltaSeconds);

	// Draw debug lines on editor
	DebugLines();

	// Render EgoVehicle dashboard
	UpdateDash();

	// Update autopilot variable
	bAutopilotEnabled = AI_Player->IsAutopilotEnabled();

	// Update the steering wheel to be responsive to user input
	TickSteeringWheel(DeltaSeconds);

	if (Pawn)
	{
		// Draw the spectator vr screen and overlay elements
		Pawn->DrawSpectatorScreen(EgoSensor->GetData()->GetGazeOrigin(DReyeVR::Gaze::LEFT),
			EgoSensor->GetData()->GetGazeDir(DReyeVR::Gaze::LEFT));

		// draws combined reticle
		Pawn->DrawFlatHUD(DeltaSeconds, EgoSensor->GetData()->GetGazeOrigin(), EgoSensor->GetData()->GetGazeDir());
	}

	// Update the world level
	TickLevel(DeltaSeconds);

	// Play sound that requires constant ticking
	TickSounds();
	UE_LOG(LogTemp, Log, TEXT("Autopilot enabled: %d"), AI_Player->IsAutopilotEnabled());
}

/// ========================================== ///
/// ----------------:CAMERA:------------------ ///
/// ========================================== ///

void AEgoVehicle::ConstructCameraRoot()
{
	// Spawn the RootComponent and Camera for the VR camera
	VRCameraRoot = CreateDefaultSubobject<USceneComponent>(TEXT("VRCameraRoot"));
	VRCameraRoot->SetupAttachment(GetRootComponent()); // The vehicle blueprint itself

	// First, set the root of the camera to the driver's seat head pos
	VRCameraRoot->SetRelativeLocation(CameraLocnInVehicle);
}

void AEgoVehicle::SetPawn(ADReyeVRPawn* PawnIn)
{
	ensure(VRCameraRoot != nullptr);
	this->Pawn = PawnIn;
	ensure(Pawn != nullptr);
	this->FirstPersonCam = Pawn->GetCamera();
	ensure(FirstPersonCam != nullptr);
	FAttachmentTransformRules F(EAttachmentRule::KeepRelative, false);
	Pawn->AttachToComponent(VRCameraRoot, F);
	Pawn->GetCamera()->AttachToComponent(VRCameraRoot, F);
	// Then set the actual camera to be at its origin (attached to VRCameraRoot)
	FirstPersonCam->SetRelativeLocation(FVector::ZeroVector);
	FirstPersonCam->SetRelativeRotation(FRotator::ZeroRotator);
}

const UCameraComponent* AEgoVehicle::GetCamera() const
{
	return FirstPersonCam;
}
UCameraComponent* AEgoVehicle::GetCamera()
{
	return FirstPersonCam;
}
FVector AEgoVehicle::GetCameraOffset() const
{
	return VRCameraRoot->GetComponentLocation();
}
FVector AEgoVehicle::GetCameraPosn() const
{
	return GetCamera()->GetComponentLocation();
}
FVector AEgoVehicle::GetNextCameraPosn(const float DeltaSeconds) const
{
	// usually only need this is tick before physics
	return GetCameraPosn() + DeltaSeconds * GetVelocity();
}
FRotator AEgoVehicle::GetCameraRot() const
{
	return GetCamera()->GetComponentRotation();
}

/// ========================================== ///
/// ---------------:AIPLAYER:----------------- ///
/// ========================================== ///

void AEgoVehicle::InitAIPlayer()
{
	AI_Player = Cast<AWheeledVehicleAIController>(this->GetController());
	ensure(AI_Player != nullptr);
}

void AEgoVehicle::SetAutopilot(const bool AutopilotOn)
{
	bAutopilotEnabled = AutopilotOn;
	AI_Player->SetAutopilot(bAutopilotEnabled);
	AI_Player->SetStickyControl(bAutopilotEnabled);
}

bool AEgoVehicle::GetAutopilotStatus() const
{
	return bAutopilotEnabled;
}

/// ========================================== ///
/// ----------------:SENSOR:------------------ ///
/// ========================================== ///

void AEgoVehicle::InitSensor()
{
	// Spawn the EyeTracker Carla sensor and attach to Ego-Vehicle:
	FActorSpawnParameters EyeTrackerSpawnInfo;
	EyeTrackerSpawnInfo.Owner = this;
	EyeTrackerSpawnInfo.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
	EgoSensor = World->SpawnActor<AEgoSensor>(GetCameraPosn(), FRotator::ZeroRotator, EyeTrackerSpawnInfo);
	check(EgoSensor != nullptr);
	// Attach the EgoSensor as a child to the EgoVehicle
	EgoSensor->AttachToActor(this, FAttachmentTransformRules::KeepRelativeTransform);
	EgoSensor->SetEgoVehicle(this);
	if (DReyeVRLevel)
		EgoSensor->SetLevel(DReyeVRLevel);
}

void AEgoVehicle::ReplayTick()
{
	const bool bIsReplaying = EgoSensor->IsReplaying();
	// need to enable/disable VehicleMesh simulation
	class USkeletalMeshComponent* VehicleMesh = GetMesh();
	if (VehicleMesh)
		VehicleMesh->SetSimulatePhysics(!bIsReplaying); // disable physics when replaying (teleporting)
	if (FirstPersonCam)
		FirstPersonCam->bLockToHmd = !bIsReplaying; // only lock orientation and position to HMD when not replaying

	// perform all sensor updates that occur when replaying
	if (bIsReplaying)
	{
		// this gets reached when the simulator is replaying data from a carla log
		const DReyeVR::AggregateData* Replay = EgoSensor->GetData();

		// include positional update here, else there is lag/jitter between the camera and the vehicle
		// since the Carla Replayer tick differs from the EgoVehicle tick
		const FTransform ReplayTransform(Replay->GetVehicleRotation(), // FRotator (Rotation)
			Replay->GetVehicleLocation(), // FVector (Location)
			FVector::OneVector);          // FVector (Scale3D)
// see https://docs.unrealengine.com/4.26/en-US/API/Runtime/Engine/Engine/ETeleportType/
		SetActorTransform(ReplayTransform, false, nullptr, ETeleportType::TeleportPhysics);

		// assign first person camera orientation and location (absolute)
		const FTransform ReplayCameraTransAbs(Replay->GetCameraRotationAbs(), // FRotator (Rotation)
			Replay->GetCameraLocationAbs(), // FVector (Location)
			FVector::OneVector);            // FVector (Scale3D)
		FirstPersonCam->SetWorldTransform(ReplayCameraTransAbs, false, nullptr, ETeleportType::TeleportPhysics);

		// overwrite vehicle inputs to use the replay data
		VehicleInputs = Replay->GetUserInputs();
	}
}

void AEgoVehicle::UpdateSensor(const float DeltaSeconds)
{
	// Explicitly update the EgoSensor here, synchronized with EgoVehicle tick
	EgoSensor->ManualTick(DeltaSeconds); // Ensures we always get the latest data

	// Calculate gaze data (in world space) using eye tracker data
	const DReyeVR::AggregateData* Data = EgoSensor->GetData();
	// Compute World positions and orientations
	const FRotator WorldRot = FirstPersonCam->GetComponentRotation();
	const FVector WorldPos = FirstPersonCam->GetComponentLocation();

	// First get the gaze origin and direction and vergence from the EyeTracker Sensor
	const float RayLength = FMath::Max(1.f, Data->GetGazeVergence() / 100.f); // vergence to m (from cm)
	const float VRMeterScale = 100.f;

	// Both eyes
	CombinedGaze = RayLength * VRMeterScale * Data->GetGazeDir();
	CombinedOrigin = WorldPos + WorldRot.RotateVector(Data->GetGazeOrigin());

	// Left eye
	LeftGaze = RayLength * VRMeterScale * Data->GetGazeDir(DReyeVR::Gaze::LEFT);
	LeftOrigin = WorldPos + WorldRot.RotateVector(Data->GetGazeOrigin(DReyeVR::Gaze::LEFT));

	// Right eye
	RightGaze = RayLength * VRMeterScale * Data->GetGazeDir(DReyeVR::Gaze::RIGHT);
	RightOrigin = WorldPos + WorldRot.RotateVector(Data->GetGazeOrigin(DReyeVR::Gaze::RIGHT));
}

/// ========================================== ///
/// ----------------:MIRROR:------------------ ///
/// ========================================== ///

void AEgoVehicle::MirrorParams::Initialize(class UStaticMeshComponent* MirrorSM,
	class UPlanarReflectionComponent* Reflection,
	class USkeletalMeshComponent* VehicleMesh)
{
	UE_LOG(LogTemp, Log, TEXT("Initializing %s mirror"), *Name)

		check(MirrorSM != nullptr);
	MirrorSM->SetupAttachment(VehicleMesh);
	MirrorSM->SetRelativeLocation(MirrorPos);
	MirrorSM->SetRelativeRotation(MirrorRot);
	MirrorSM->SetRelativeScale3D(MirrorScale);
	MirrorSM->SetGenerateOverlapEvents(false); // don't collide with itself
	MirrorSM->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	MirrorSM->SetVisibility(true);

	check(Reflection != nullptr);
	Reflection->SetupAttachment(MirrorSM);
	Reflection->SetRelativeLocation(ReflectionPos);
	Reflection->SetRelativeRotation(ReflectionRot);
	Reflection->SetRelativeScale3D(ReflectionScale);
	Reflection->NormalDistortionStrength = 0.0f;
	Reflection->PrefilterRoughness = 0.0f;
	Reflection->DistanceFromPlaneFadeoutStart = 1500.f;
	Reflection->DistanceFromPlaneFadeoutEnd = 0.f;
	Reflection->AngleFromPlaneFadeStart = 0.f;
	Reflection->AngleFromPlaneFadeEnd = 90.f;
	Reflection->PrefilterRoughnessDistance = 10000.f;
	Reflection->ScreenPercentage = ScreenPercentage; // change this to reduce quality & improve performance
	Reflection->bShowPreviewPlane = false;
	Reflection->HideComponent(VehicleMesh);
	Reflection->SetVisibility(true);
	/// TODO: use USceneCaptureComponent::ShowFlags to define what gets rendered in the mirror
	// https://docs.unrealengine.com/4.27/en-US/API/Runtime/Engine/FEngineShowFlags/
}

void AEgoVehicle::ConstructMirrors()
{

	class USkeletalMeshComponent* VehicleMesh = GetMesh();
	/// Rear mirror
	if (RearMirrorParams.Enabled)
	{
		static ConstructorHelpers::FObjectFinder<UStaticMesh> RearSM(
			TEXT("StaticMesh'/Game/Carla/Blueprints/Vehicles/DReyeVR/Mirrors/"
				"RearMirror_DReyeVR_Glass_SM.RearMirror_DReyeVR_Glass_SM'"));
		RearMirrorSM = CreateDefaultSubobject<UStaticMeshComponent>(FName(*(RearMirrorParams.Name + "MirrorSM")));
		RearMirrorSM->SetStaticMesh(RearSM.Object);
		RearReflection = CreateDefaultSubobject<UPlanarReflectionComponent>(FName(*(RearMirrorParams.Name + "Refl")));
		RearMirrorParams.Initialize(RearMirrorSM, RearReflection, VehicleMesh);
		// also add the chassis for this mirror
		static ConstructorHelpers::FObjectFinder<UStaticMesh> RearChassisSM(TEXT(
			"StaticMesh'/Game/Carla/Blueprints/Vehicles/DReyeVR/Mirrors/RearMirror_DReyeVR_SM.RearMirror_DReyeVR_SM'"));
		RearMirrorChassisSM =
			CreateDefaultSubobject<UStaticMeshComponent>(FName(*(RearMirrorParams.Name + "MirrorChassisSM")));
		RearMirrorChassisSM->SetStaticMesh(RearChassisSM.Object);
		RearMirrorChassisSM->SetupAttachment(VehicleMesh);
		RearMirrorChassisSM->SetRelativeLocation(RearMirrorChassisPos);
		RearMirrorChassisSM->SetRelativeRotation(RearMirrorChassisRot);
		RearMirrorChassisSM->SetRelativeScale3D(RearMirrorChassisScale);
		RearMirrorChassisSM->SetGenerateOverlapEvents(false); // don't collide with itself
		RearMirrorChassisSM->SetCollisionEnabled(ECollisionEnabled::NoCollision);
		RearMirrorChassisSM->SetVisibility(true);
		RearMirrorSM->SetupAttachment(RearMirrorChassisSM);
		RearReflection->HideComponent(RearMirrorChassisSM); // don't show this in the reflection
	}
	/// Left mirror
	if (LeftMirrorParams.Enabled)
	{
		static ConstructorHelpers::FObjectFinder<UStaticMesh> LeftSM(TEXT(
			"StaticMesh'/Game/Carla/Blueprints/Vehicles/DReyeVR/Mirrors/LeftMirror_DReyeVR_SM.LeftMirror_DReyeVR_SM'"));
		LeftMirrorSM = CreateDefaultSubobject<UStaticMeshComponent>(FName(*(LeftMirrorParams.Name + "MirrorSM")));
		LeftMirrorSM->SetStaticMesh(LeftSM.Object);
		LeftReflection = CreateDefaultSubobject<UPlanarReflectionComponent>(FName(*(LeftMirrorParams.Name + "Refl")));
		LeftMirrorParams.Initialize(LeftMirrorSM, LeftReflection, VehicleMesh);
	}
	/// Right mirror
	if (RightMirrorParams.Enabled)
	{
		static ConstructorHelpers::FObjectFinder<UStaticMesh> RightSM(
			TEXT("StaticMesh'/Game/Carla/Blueprints/Vehicles/DReyeVR/Mirrors/"
				"RightMirror_DReyeVR_SM.RightMirror_DReyeVR_SM'"));
		RightMirrorSM = CreateDefaultSubobject<UStaticMeshComponent>(FName(*(RightMirrorParams.Name + "MirrorSM")));
		RightMirrorSM->SetStaticMesh(RightSM.Object);
		RightReflection = CreateDefaultSubobject<UPlanarReflectionComponent>(FName(*(RightMirrorParams.Name + "Refl")));
		RightMirrorParams.Initialize(RightMirrorSM, RightReflection, VehicleMesh);
	}
}

/// ========================================== ///
/// ----------------:SOUNDS:------------------ ///
/// ========================================== ///

void AEgoVehicle::ConstructEgoSounds()
{
	// Initialize ego-centric audio components
	// See ACarlaWheeledVehicle::ConstructSounds for all Vehicle sounds
	ensureMsgf(EngineRevSound != nullptr, TEXT("Vehicle engine rev should be initialized!"));
	ensureMsgf(CrashSound != nullptr, TEXT("Vehicle crash sound should be initialized!"));

	static ConstructorHelpers::FObjectFinder<USoundWave> GearSound(
		TEXT("SoundWave'/Game/Carla/Blueprints/Vehicles/DReyeVR/Sounds/GearShift.GearShift'"));
	GearShiftSound = CreateDefaultSubobject<UAudioComponent>(TEXT("GearShift"));
	GearShiftSound->SetupAttachment(GetRootComponent());
	GearShiftSound->bAutoActivate = false;
	GearShiftSound->SetSound(GearSound.Object);

	static ConstructorHelpers::FObjectFinder<USoundWave> TurnSignalSoundWave(
		TEXT("SoundWave'/Game/Carla/Blueprints/Vehicles/DReyeVR/Sounds/TurnSignal.TurnSignal'"));
	TurnSignalSound = CreateDefaultSubobject<UAudioComponent>(TEXT("TurnSignal"));
	TurnSignalSound->SetupAttachment(GetRootComponent());
	TurnSignalSound->bAutoActivate = false;
	TurnSignalSound->SetSound(TurnSignalSoundWave.Object);

	static ConstructorHelpers::FObjectFinder<USoundWave> TORAlertSoundWave(
		TEXT("SoundWave'/Game/Carla/Blueprints/Vehicles/DReyeVR/Sounds/AlertSound.AlertSound'"));
	TORAlertSound = CreateDefaultSubobject<UAudioComponent>(TEXT("TORAlert"));
	TORAlertSound->SetupAttachment(GetRootComponent());
	TORAlertSound->bAutoActivate = false;
	TORAlertSound->SetSound(TORAlertSoundWave.Object);
}
void AEgoVehicle::PlayTORAlertSound(const float DelayBeforePlay) const
{
	if (!(this->TORAlertSound->IsPlaying()))
		TORAlertSound->Play(DelayBeforePlay);
}

void AEgoVehicle::PlayGearShiftSound(const float DelayBeforePlay) const
{
	if (this->GearShiftSound)
		GearShiftSound->Play(DelayBeforePlay);
}

void AEgoVehicle::PlayTurnSignalSound(const float DelayBeforePlay) const
{
	if (this->TurnSignalSound)
		this->TurnSignalSound->Play(DelayBeforePlay);
}

void AEgoVehicle::SetVolume(const float VolumeIn)
{
	if (GearShiftSound)
		GearShiftSound->SetVolumeMultiplier(VolumeIn);
	if (TurnSignalSound)
		TurnSignalSound->SetVolumeMultiplier(VolumeIn);
	Super::SetVolume(VolumeIn);
}

/// ========================================== ///
/// -----------------:DASH:------------------- ///
/// ========================================== ///

void AEgoVehicle::ConstructDashText() // dashboard text (speedometer, turn signals, gear shifter)
{
	// Create speedometer
	Speedometer = CreateDefaultSubobject<UTextRenderComponent>(TEXT("Speedometer"));
	Speedometer->AttachToComponent(GetRootComponent(), FAttachmentTransformRules::KeepRelativeTransform);
	Speedometer->SetRelativeLocation(DashboardLocnInVehicle);
	Speedometer->SetRelativeRotation(FRotator(0.f, 180.f, 0.f)); // need to flip it to get the text in driver POV
	Speedometer->SetTextRenderColor(FColor::Red);
	Speedometer->SetText(FText::FromString("0"));
	Speedometer->SetXScale(1.f);
	Speedometer->SetYScale(1.f);
	Speedometer->SetWorldSize(10); // scale the font with this
	Speedometer->SetVerticalAlignment(EVerticalTextAligment::EVRTA_TextCenter);
	Speedometer->SetHorizontalAlignment(EHorizTextAligment::EHTA_Center);
	SpeedometerScale = CmPerSecondToXPerHour(bUseMPH);

	// Create turn signals
	TurnSignals = CreateDefaultSubobject<UTextRenderComponent>(TEXT("TurnSignals"));
	TurnSignals->AttachToComponent(GetRootComponent(), FAttachmentTransformRules::KeepRelativeTransform);
	TurnSignals->SetRelativeLocation(DashboardLocnInVehicle + FVector(0, 11.f, -5.f));
	TurnSignals->SetRelativeRotation(FRotator(0.f, 180.f, 0.f)); // need to flip it to get the text in driver POV
	TurnSignals->SetTextRenderColor(FColor::Red);
	TurnSignals->SetText(FText::FromString(""));
	TurnSignals->SetXScale(1.f);
	TurnSignals->SetYScale(1.f);
	TurnSignals->SetWorldSize(10); // scale the font with this
	TurnSignals->SetVerticalAlignment(EVerticalTextAligment::EVRTA_TextCenter);
	TurnSignals->SetHorizontalAlignment(EHorizTextAligment::EHTA_Center);

	// Create gear shifter
	GearShifter = CreateDefaultSubobject<UTextRenderComponent>(TEXT("GearShifter"));
	GearShifter->AttachToComponent(GetRootComponent(), FAttachmentTransformRules::KeepRelativeTransform);
	GearShifter->SetRelativeLocation(DashboardLocnInVehicle + FVector(0, 15.f, 0));
	GearShifter->SetRelativeRotation(FRotator(0.f, 180.f, 0.f)); // need to flip it to get the text in driver POV
	GearShifter->SetTextRenderColor(FColor::Red);
	GearShifter->SetText(FText::FromString("D"));
	GearShifter->SetXScale(1.f);
	GearShifter->SetYScale(1.f);
	GearShifter->SetWorldSize(10); // scale the font with this
	GearShifter->SetVerticalAlignment(EVerticalTextAligment::EVRTA_TextCenter);
	GearShifter->SetHorizontalAlignment(EHorizTextAligment::EHTA_Center);

	//  Constructing User-Interface
	ConstructInterface();
}

void AEgoVehicle::RetriveText()
{
	FString PathToTextFile = FString::Printf(TEXT("%s/ConfigFiles/%s.txt"), *FPaths::ProjectContentDir(), *TextFileName);
	TArray<FString> Paragraphs;
	FFileHelper::LoadFileToStringArray(Paragraphs, *PathToTextFile);
	FString TextFString = FString::Join(Paragraphs, TEXT(""));
	TextStdString = std::string(TCHAR_TO_UTF8(*TextFString));
	for (FString Sentence : Paragraphs)
	{
		TArray<FString> Words;
		Sentence.ParseIntoArray(Words, TEXT(" "), true);
		TextWordsArray.Append(Words);
	}
}

void AEgoVehicle::UpdateDash()
{
	// Draw text components
	float XPH; // miles-per-hour or km-per-hour
	if (EgoSensor->IsReplaying())
	{
		const DReyeVR::AggregateData* Replay = EgoSensor->GetData();
		XPH = Replay->GetVehicleVelocity() * SpeedometerScale; // FwdSpeed is in cm/s
		if (Replay->GetUserInputs().ToggledReverse)
		{
			bReverse = !bReverse;
			PlayGearShiftSound();
		}
		if (bEnableTurnSignalAction)
		{
			if (Replay->GetUserInputs().TurnSignalLeft)
			{
				LeftSignalTimeToDie = FPlatformTime::Seconds() + TurnSignalDuration;
				RightSignalTimeToDie = 0.f;
				PlayTurnSignalSound();
			}
			if (Replay->GetUserInputs().TurnSignalRight)
			{
				RightSignalTimeToDie = FPlatformTime::Seconds() + TurnSignalDuration;
				LeftSignalTimeToDie = 0.f;
				PlayTurnSignalSound();
			}
		}
	}
	else
	{
		XPH = GetVehicleForwardSpeed() * SpeedometerScale; // FwdSpeed is in cm/s
	}

	const FString Data = FString::FromInt(int(FMath::RoundHalfFromZero(XPH)));
	Speedometer->SetText(FText::FromString(Data));

	if (bEnableTurnSignalAction)
	{
		// Draw the signals
		float Now = FPlatformTime::Seconds();
		if (Now < RightSignalTimeToDie)
			TurnSignals->SetText(FText::FromString(">>>"));
		else if (Now < LeftSignalTimeToDie)
			TurnSignals->SetText(FText::FromString("<<<"));
		else
			TurnSignals->SetText(FText::FromString("")); // nothing
	}

	// Draw the gear shifter
	if (bReverse)
		GearShifter->SetText(FText::FromString("R"));
	else
		GearShifter->SetText(FText::FromString("D"));

	// Reading the Signal File to modify the control variables
	int32 signal = ReadSignalFile();
	if (signal == 0)
	{
		// Python Script is executed, start reading task
		bStartNDRT = true;
	}
	else if (signal == 1) {
		// TOE is issued, pause the NDRT
		bIsNDRTPaused = true;
	}
	if (bStartNDRT && !bIsNDRTComplete && !bIsNDRTPaused) {
		/*
		* Enable Text-to-Speech if wanted and if not enabled yet
		NOTE: Using Engine to Run TTS is disabled for nowand client side scripts must be used!
		if (bTTS && !bThreadInit) {
			EnableTextToSpeech();
			bThreadInit = true;
		}
		*/
		// Make the HUD visible and restoring default text styles just in case if it was made hidden
		HUD->SetVisibility(true, false);
		RestoreNDRTStyling();

		// Updating text in the Heads-Up Display
		if (bRSVP) {
			RSVPTTS();
		}
		else {
			STPTTS();
		}
		// There are also other methods such as the RSVP() and STP() which dont require the words from the TTS stream. The what fixed time budget for every word/line.
	}
	// If NDRT is paused case
	if (bIsNDRTPaused) {
		// Display TOR Alert Message: "Take Manual Control"
		DisplayHUDAlert(TEXT("EMERGENCY\nTake Manual Control"), FColor::Red);

		//const FLinearColor MsgColour = FLinearColor(0, 1, 1, 1); // YELLOW
		//UKismetSystemLibrary::PrintString(World, FString::Printf(TEXT("NDRT Paused")), true, false, MsgColour, 1.f);

		if (!bIsTORComplete)
		{
			// Scenario when NDRT is paused and TOR is not complete
			//const FLinearColor MsgColour = FLinearColor(0, 1, 1, 1); // YELLOW
			//UKismetSystemLibrary::PrintString(World, FString::Printf(TEXT("TOR Running: %s"), bIsTORComplete ? TEXT("t") : TEXT("f")), true, false, MsgColour, 1.f);
			// This means TOR is not fulfilled yet.
			PlayTORAlertSound();
			// Check is TOR is complete or not
			bIsTORComplete = ReadSignalFile() == 2 ? true : bIsTORComplete;
			// If the TOR was just fulfilled, create future time stamp
			if (bIsTORComplete) {
				NDRTPauseOverFutureTimeStamp = World->GetTimeSeconds() + 3;
				// Destory the TOR Alert sound after the TOR is fulfilled.
				TORAlertSound->DestroyComponent();
			}
		}
		else {
			// If TOR is complete, display "Autopilot enable, resuming reading task" for 3 seconds
			if (NDRTPauseOverFutureTimeStamp > World->GetTimeSeconds()) {
				DisplayHUDAlert(TEXT("Autopilot Enabled\nResuming Reading Task"), FColor::Blue);
			}
			else {
				bIsNDRTPaused = false;
				// Now, the reading task should resume! Restore the default reading task styling
				// Reset the text display just in case to avoid displaying it on HUD with running reading task
				TextDisplay->SetText("");
			}
		}
	}
	else if (bIsNDRTComplete)
	{
		//const FLinearColor MsgColour = FLinearColor(0, 1, 1, 1); // YELLOW
		//UKismetSystemLibrary::PrintString(World, FString::Printf(TEXT("NDRT completed")), true, false, MsgColour, 1.f);
		// If NDRT is Complete, End the study
		DisplayHUDAlert(TEXT("Reading Task\nis complete"), FColor::Green);
		// Signal "3" should have been written in the signal file by this time.
	}
}

void AEgoVehicle::STP()
{
	if (bIsFirst)
	{
		for (int32 i = 0; i < 2; i++)
			CurrentLines.Emplace(FString(TEXT(" \n")));
		for (int32 i = 0; i < 4; i++)
			CurrentLines.Emplace(GenerateSentence());
		SetTextSTP();
		bIsFirst = false;
		FutureTimeStamp = World->GetTimeSeconds() + LineShiftIntervals[CurrentLineIndex++];
	}
	else if (FutureTimeStamp <= World->GetTimeSeconds())
	{
		// Shifting a line up i.e., removing first line and appending the next line;
		CurrentLines.RemoveAt(0);
		CurrentLines.Emplace(GenerateSentence());
		SetTextSTP();
		FutureTimeStamp = World->GetTimeSeconds() + LineShiftIntervals[CurrentLineIndex++];
	}
	if (EmptyGeneratedTexts >= 4) {
		bIsNDRTComplete = true;
		// Send Signal to PythonAPI that NDRT is complete
		WriteSignalFile(TEXT("3"));
	}
}

void AEgoVehicle::STPTTS()
{
	if (bIsFirst)
	{
		for (int32 i = 0; i < 2; i++)
			CurrentLines.Emplace(FString(TEXT(" \n")));
		for (int32 i = 0; i < 4; i++)
			CurrentLines.Emplace(GenerateSentence());
		SetTextSTP();
		bIsFirst = false;
	}
	else
	{
		// Only shift the line if the current TTS word being spoken is not in the first line.
		// Do not check for if the TOR is complete or not here. Done later

		FString TTSStreamWord = ReadTTSStreamFile();
		TArray<FString> StreamWords;
		TTSStreamWord.ParseIntoArray(StreamWords, TEXT(" "), true);

		const FLinearColor MsgColour = FLinearColor(0, 1, 1, 1); // YELLOW
		//UKismetSystemLibrary::PrintString(World, FString::Printf(TEXT("\"%s\" ||| %s"), *TTSStreamWord, *CurrentLines[0]), true, false, MsgColour, 1.f);

		// Checking if scrolling is required or not
		// Do not scroll if:
		// 1. Multiple words are spoken (Some words may be on the second line leading to unwanted swift scrolling)
		// 2. Stream word is empty
		// 3. The current line contains the stream word
		if (StreamWords.Num() == 1 && !TTSStreamWord.IsEmpty() && !CurrentLines[2].Contains(TTSStreamWord, ESearchCase::IgnoreCase, ESearchDir::FromStart) && bFoundAMatch) {
			// Shifting a line up i.e., removing first line and appending the next line;
			CurrentLines.RemoveAt(0);
			CurrentLines.Emplace(GenerateSentence());
			SetTextSTP();
		}
		else
		{
			bFoundAMatch = true;
		}
	}
	std::string Flag = "TTSOver";
	if (ReadTTSStreamFile().Equals(Flag.c_str())) {
		bIsNDRTComplete = true;
		// Send Signal to PythonAPI that NDRT is complete
		WriteSignalFile(TEXT("3"));
	}
}

void AEgoVehicle::RSVP()
{
	if (bIsFirst) {
		FString Word = TextWordsArray[EndIndex];
		TextDisplay->SetText(Word);
		bIsFirst = false;
		EndIndex++;
		FutureTimeStamp = World->GetTimeSeconds() + (60.f / WPM);
	}
	else if (FutureTimeStamp <= World->GetTimeSeconds() && EndIndex < TextWordsArray.Num()) {
		FString Word = TextWordsArray[EndIndex];
		TextDisplay->SetText(Word);
		EndIndex++;
		FutureTimeStamp = World->GetTimeSeconds() + (60.f / WPM);
	}

	if (EndIndex >= TextWordsArray.Num())
	{
		bIsNDRTComplete = true;
		// Send Signal to PythonAPI that the reading task is over.
		WriteSignalFile(TEXT("3"));
	}
}

void AEgoVehicle::RSVPTTS()
{
	// Read the RSVP stream file
	FString Word = ReadTTSStreamFile();

	// If the signal of TTS being over is received, terminate.
	std::string Flag = "TTSOver";
	if (Word.Equals(Flag.c_str())) {
		bIsNDRTComplete = true;
		// Send Signal to PythonAPI that the reading task is over.
		WriteSignalFile(TEXT("3"));
	}
	else
	{
		// else update the RSVP interface with the new word
		TextDisplay->SetText(Word);
	}
}

FString AEgoVehicle::GenerateSentence()
{
	int32 CharacterSum = 0;
	int32 WordCount = 0;
	FString Sentence = TEXT("");
	while (EndIndex < TextWordsArray.Num()) {
		FString Word = TextWordsArray[EndIndex];
		CharacterSum += Word.Len();
		if (CharacterSum >= CharacterLimit)
			break;
		Sentence.Append(Word);
		Sentence.Append(TEXT(" "));
		EndIndex++;
		WordCount++;
	}
	Sentence.Append(TEXT("\n"));

	// Adding the line shift time budget to an array
	LineShiftIntervals.Emplace((60.f / WPM) * WordCount);

	// Checking if the secondary task is complete
	if (EndIndex >= TextWordsArray.Num())
	{
		EmptyGeneratedTexts++;
	}
	return Sentence;
}
void AEgoVehicle::SetTextSTP()
{
	FString TextToSet = TEXT("");
	for (FString line : CurrentLines)
		TextToSet.Append(line);
	TextDisplay->SetText(TextToSet);
}
void AEgoVehicle::ConstructInterface() {
	// Creating a Heads-Up display
	HUD = CreateDefaultSubobject<UStaticMeshComponent>(TEXT("HUD"));
	HUD->AttachToComponent(GetRootComponent(), FAttachmentTransformRules::KeepRelativeTransform);
	HUD->SetCollisionEnabled(ECollisionEnabled::NoCollision);

	// Creating a text display interface
	TextDisplay = CreateDefaultSubobject<UTextRenderComponent>(TEXT("TextDisplay"));
	TextDisplay->AttachToComponent(GetRootComponent(), FAttachmentTransformRules::KeepRelativeTransform);
	TextDisplay->SetTextRenderColor(FColor::Black);
	TextDisplay->SetXScale(1.f);
	TextDisplay->SetYScale(1.f);

	// Settings conditional to Text presentation technique.
	if (bRSVP) {
		HUD->SetRelativeLocation(DashboardLocnInVehicle + FVector(5, -45.f, 40.f));
		FString PathToMesh = TEXT("StaticMesh'/Game/DReyeVROFR/StaticMeshes/RSVP_HUD_v1.RSVP_HUD_v1'");
		const ConstructorHelpers::FObjectFinder<UStaticMesh> MeshObj(*PathToMesh);
		HUD->SetStaticMesh(MeshObj.Object);

		TextDisplay->SetRelativeLocation(DashboardLocnInVehicle + FVector(-7, -45, 37.f));
		TextDisplay->SetRelativeRotation(FRotator(-32.f, 180.f, 0.f)); // need to flip it to get the text in driver POV
		TextDisplay->SetWorldSize(4); // scale the font with this
		TextDisplay->SetVerticalAlignment(EVerticalTextAligment::EVRTA_TextCenter);
		TextDisplay->SetHorizontalAlignment(EHorizTextAligment::EHTA_Center);
	}
	else {
		UE_LOG(LogTemp, Log, TEXT("DEBUG: Choosing STP"));
		HUD->SetRelativeLocation(DashboardLocnInVehicle + FVector(5, -45.f, 37.f));
		FString PathToMesh = TEXT("StaticMesh'/Game/DReyeVROFR/StaticMeshes/STP_HUD_v1.STP_HUD_v1'");
		const ConstructorHelpers::FObjectFinder<UStaticMesh> MeshObj(*PathToMesh);
		HUD->SetStaticMesh(MeshObj.Object);

		TextDisplay->SetRelativeLocation(DashboardLocnInVehicle + FVector(-7, -66.5f, 46.f));
		TextDisplay->SetRelativeRotation(FRotator(-32.f, 180.f, 0.f)); // need to flip it to get the text in driver POV
		TextDisplay->SetWorldSize(4); // scale the font with this
		TextDisplay->SetVerticalAlignment(EVerticalTextAligment::EVRTA_TextTop);
		TextDisplay->SetHorizontalAlignment(EHorizTextAligment::EHTA_Left);
	}
}
void AEgoVehicle::RestoreNDRTStyling() {
	TextDisplay->SetTextRenderColor(FColor::Black);
	TextDisplay->SetXScale(1.f);
	TextDisplay->SetYScale(1.f);

	// Settings conditional to Text presentation technique.
	if (bRSVP) {
		TextDisplay->SetRelativeLocation(DashboardLocnInVehicle + FVector(-7, -45, 37.f));
		TextDisplay->SetRelativeRotation(FRotator(-32.f, 180.f, 0.f)); // need to flip it to get the text in driver POV
		TextDisplay->SetWorldSize(4); // scale the font with this
		TextDisplay->SetVerticalAlignment(EVerticalTextAligment::EVRTA_TextCenter);
		TextDisplay->SetHorizontalAlignment(EHorizTextAligment::EHTA_Center);
	}
	else {
		TextDisplay->SetRelativeLocation(DashboardLocnInVehicle + FVector(-7, -66.5f, 46.f));
		TextDisplay->SetRelativeRotation(FRotator(-32.f, 180.f, 0.f)); // need to flip it to get the text in driver POV
		TextDisplay->SetWorldSize(4); // scale the font with this
		TextDisplay->SetVerticalAlignment(EVerticalTextAligment::EVRTA_TextTop);
		TextDisplay->SetHorizontalAlignment(EHorizTextAligment::EHTA_Left);
	}
}
void AEgoVehicle::EnableTextToSpeech() {
	FTTSThread* TTSThread = new FTTSThread(TextStdString, WPM);
}

void AEgoVehicle::ReadSettingsFile() {
	const FString Settings = FPaths::ProjectContentDir() / TEXT("ConfigFiles/config.txt");
	FString Result;
	FFileHelper::LoadFileToString(Result, *Settings);

	// Reading file: RSVP behaviour should be enabled or not
	FString RSVP = UKismetStringLibrary::GetSubstring(Result, Result.Find(TEXT("RSVP:"), ESearchCase::IgnoreCase, ESearchDir::FromStart) + 6, 1);
	FString WPMString = UKismetStringLibrary::GetSubstring(Result, Result.Find(TEXT("WPM:"), ESearchCase::IgnoreCase, ESearchDir::FromStart) + 5, 3);
	FString TTS = UKismetStringLibrary::GetSubstring(Result, Result.FString::Find(TEXT("TTS:"), ESearchCase::IgnoreCase, ESearchDir::FromStart) + 5, 1);
	TextFileName = UKismetStringLibrary::GetSubstring(Result, Result.FString::Find(TEXT("TEXTFILE:"), ESearchCase::IgnoreCase, ESearchDir::FromStart) + 10, 5);
	if (RSVP.Equals("0")) {
		bRSVP = false;
	}
	else {
		bRSVP = true;
	}

	if (TTS.Equals("0")) {
		bTTS = false;
	}
	else {
		bTTS = true;
	}
	WPM = UKismetStringLibrary::Conv_StringToInt(WPMString);
}

FString AEgoVehicle::ReadTTSStreamFile() {
	const FString TTSStreamFilePath = FPaths::ProjectContentDir() / TEXT("ConfigFiles/TTSStreamFile.txt");
	FString Result;
	FFileHelper::LoadFileToString(Result, *TTSStreamFilePath);
	return Result;
}

void AEgoVehicle::ResetTTSStreamFile()
{
	const FString TTSStreamFilePath = FPaths::ProjectContentDir() / TEXT("ConfigFiles/TTSStreamFile.txt");
	FFileHelper::SaveStringToFile(TEXT(""), *TTSStreamFilePath, FFileHelper::EEncodingOptions::AutoDetect, &IFileManager::Get());
}

/// ========================================== ///
/// ------------------:TOR:------------------- ///
/// ========================================== ///

void AEgoVehicle::DisplayHUDAlert(FString DisplayText, FColor TextColor) {
	// Hide the Heads-Up Display
	HUD->SetVisibility(false, false);

	// Displaying the TOR alert message
	TextDisplay->SetRelativeLocation(DashboardLocnInVehicle + FVector(-7, -45, 37.f));
	TextDisplay->SetVerticalAlignment(EVerticalTextAligment::EVRTA_TextCenter);
	TextDisplay->SetHorizontalAlignment(EHorizTextAligment::EHTA_Center);
	TextDisplay->SetWorldSize(8); // scale the font with this
	TextDisplay->SetTextRenderColor(TextColor);
	TextDisplay->SetText(DisplayText);
}

void AEgoVehicle::WriteSignalFile(const FString& signal)
{
	const FString SignalFilePath = FPaths::ProjectContentDir() / TEXT("ConfigFiles/SignalFile.txt");
	FFileHelper::SaveStringToFile(signal, *SignalFilePath, FFileHelper::EEncodingOptions::AutoDetect, &IFileManager::Get());
}

int32 AEgoVehicle::ReadSignalFile()
{
	const FString SignalFilePath = FPaths::ProjectContentDir() / TEXT("ConfigFiles/SignalFile.txt");
	FString Result;
	FFileHelper::LoadFileToString(Result, *SignalFilePath);
	return UKismetStringLibrary::Conv_StringToInt(Result);
}

/// ========================================== ///
/// -----------------:WHEEL:------------------ ///
/// ========================================== ///

void AEgoVehicle::ConstructSteeringWheel()
{
	static ConstructorHelpers::FObjectFinder<UStaticMesh> SteeringWheelSM(
		TEXT("StaticMesh'/Game/Carla/Blueprints/Vehicles/DReyeVR/SteeringWheel/"
			"SM_SteeringWheel_DReyeVR.SM_SteeringWheel_DReyeVR'"));
	SteeringWheel = CreateDefaultSubobject<UStaticMeshComponent>(FName("SteeringWheel"));
	SteeringWheel->SetStaticMesh(SteeringWheelSM.Object);
	SteeringWheel->SetupAttachment(GetRootComponent()); // The vehicle blueprint itself
	SteeringWheel->SetRelativeLocation(InitWheelLocation);
	SteeringWheel->SetRelativeRotation(InitWheelRotation);
	SteeringWheel->SetGenerateOverlapEvents(false); // don't collide with itself
	SteeringWheel->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	SteeringWheel->SetVisibility(true);
}

void AEgoVehicle::TickSteeringWheel(const float DeltaTime)
{
	const FRotator CurrentRotation = SteeringWheel->GetRelativeRotation();
	const float RawSteering = GetVehicleInputs().Steering; // this is scaled in SetSteering
	const float TargetAngle = (RawSteering / ScaleSteeringInput) * SteeringAnimScale;
	FRotator NewRotation = CurrentRotation;
	if (Pawn && Pawn->GetIsLogiConnected())
	{
		NewRotation.Roll = TargetAngle;
	}
	else
	{
		float DeltaAngle = (TargetAngle - CurrentRotation.Roll);

		// place a speed-limit on the steering wheel
		DeltaAngle = FMath::Clamp(DeltaAngle, -MaxSteerVelocity, MaxSteerVelocity);

		// create the new rotation using the deltas
		NewRotation += DeltaTime * FRotator(0.f, 0.f, DeltaAngle);

		// Clamp the roll amount so the wheel can't spin infinitely
		NewRotation.Roll = FMath::Clamp(NewRotation.Roll, -MaxSteerAngleDeg, MaxSteerAngleDeg);
	}
	SteeringWheel->SetRelativeRotation(NewRotation);
}

/// ========================================== ///
/// -----------------:LEVEL:------------------ ///
/// ========================================== ///

void AEgoVehicle::SetLevel(ADReyeVRLevel* Level)
{
	this->DReyeVRLevel = Level;
	check(DReyeVRLevel != nullptr);
}

void AEgoVehicle::TickLevel(float DeltaSeconds)
{
	if (this->DReyeVRLevel != nullptr)
		DReyeVRLevel->Tick(DeltaSeconds);
}

/// ========================================== ///
/// -----------------:OTHER:------------------ ///
/// ========================================== ///

void AEgoVehicle::Register()
{
	FCarlaActor::IdType ID = EgoVehicleID;
	FActorDescription Description;
	Description.Class = ACarlaWheeledVehicle::StaticClass();
	Description.Id = "vehicle.dreyevr.egovehicle";
	Description.UId = ID;
	// ensure this vehicle is denoted by the 'hero' attribute
	FActorAttribute HeroRole;
	HeroRole.Id = "role_name";
	HeroRole.Type = EActorAttributeType::String;
	HeroRole.Value = "hero";
	Description.Variations.Add(HeroRole.Id, std::move(HeroRole));
	// ensure the vehicle has attributes denoting number of wheels
	FActorAttribute NumWheels;
	NumWheels.Id = "number_of_wheels";
	NumWheels.Type = EActorAttributeType::Int;
	NumWheels.Value = "4";
	Description.Variations.Add(NumWheels.Id, std::move(NumWheels));
	FString RegistryTags = "EgoVehicle,DReyeVR";
	Episode->RegisterActor(*this, Description, RegistryTags, ID);
}

/// ========================================== ///
/// ---------------:COSMETIC:----------------- ///
/// ========================================== ///

void AEgoVehicle::DebugLines() const
{
#if WITH_EDITOR
	// Compute World positions and orientations
	const FRotator WorldRot = FirstPersonCam->GetComponentRotation();
	// Rotate and add the gaze ray to the origin
	FVector CombinedGazePosn = CombinedOrigin + WorldRot.RotateVector(CombinedGaze);

	// Use Absolute Ray Position to draw debug information
	if (bDrawDebugEditor)
	{
		DrawDebugSphere(World, CombinedGazePosn, 4.0f, 12, FColor::Blue);

		// Draw individual rays for left and right eye
		DrawDebugLine(World,
			LeftOrigin,                                        // start line
			LeftOrigin + 10 * WorldRot.RotateVector(LeftGaze), // end line
			FColor::Green, false, -1, 0, 1);

		DrawDebugLine(World,
			RightOrigin,                                         // start line
			RightOrigin + 10 * WorldRot.RotateVector(RightGaze), // end line
			FColor::Yellow, false, -1, 0, 1);
	}
#endif
}