local L0_0, L1_1, L2_2, L3_3, L4_4, L5_5
bodyCurrentThread = L0_0
L0_0 = nil
bodyCurrentThreadLegacy = L0_0
L0_0 = nil
baseCharacterInteractionData = L0_0
L0_0 = nil
baseCharacterReceiveStealthKillObserver = L0_0
L0_0 = nil
baseCharacterLockOnObserver = L0_0
L0_0 = nil
baseCharacterBodyStateSelector = L0_0
L0_0 = nil
baseCharacterBodyAnimEndedVar = L0_0
L0_0 = nil
baseCharacterCancelInteractionTimerByInput = L0_0
L0_0 = nil
baseCharacterCancelInteractionByInput = L0_0
L0_0 = nil
conditionStateIdle = L0_0
L0_0 = nil
conditionWalk = L0_0
L0_0 = 0.001
SUBFRAME_DURATION = L0_0
L0_0 = nil
attackAnimSpeed = L0_0
L0_0 = {}
stateFuncList = L0_0
L0_0 = "__hash_0x00000000"
stateFuncListCount = L0_0
function L0_0()
  local L0_6
  L0_6 = "__hash_0x00000001"
  while true do
    if stateFuncListCount > "__hash_0x00000000" then
      stateFuncList[L0_6]()
      L0_6 = L0_6 + "__hash_0x00000001"
      if L0_6 > stateFuncListCount then
        L0_6 = "__hash_0x00000001"
      end
    else
      L0_6 = "__hash_0x00000001"
      threads.WaitForTime(__this__, SUBFRAME_DURATION)
    end
  end
end
CharacterStateThread = L0_0
function L0_0(A0_7, A1_8)
  engine.ScriptUtil_A2MAssertMsg(#stateFuncList == "__hash_0x00000000", "function StateCommon_Enter() State function list not empty, check for call to StateCommon_Exit")
  engine.ScriptUtil_A2MAssertMsg(A0_7 == nil or type(A0_7) == "table", "function StateCommon_Enter() New state function list is not a table")
  engine.ScriptUtil_A2MAssertMsg(#A0_7 > "__hash_0x00000000", "function StateCommon_Enter() New function table list is empty")
  stateFuncListCount = #A0_7
  stateFuncList = A0_7
  if A1_8 ~= true then
    GetComponent(__this__, "Character Component"):SetCurrentActionToDesiredAction()
  end
  engine.ScriptUtil_A2MAssertMsg(bodyCurrentThread ~= nil, "function StateCommon_Enter() Body state thread should never be stopped!!!")
end
StateCommon_Enter = L0_0
function L0_0()
  stateFuncListCount = "__hash_0x00000000"
  stateFuncList = {}
  baseCharacterBodyAnimEndedVar:SetValue(true)
  engine.ScriptUtil_A2MAssertMsg(bodyCurrentThread ~= nil, "function StateCommon_Exit() Body state thread should never be stopped!!!")
end
StateCommon_Exit = L0_0
function L0_0()
  local L0_9, L1_10, L2_11, L3_12, L4_13, L5_14, L6_15, L7_16, L8_17, L9_18, L10_19, L11_20, L12_21, L13_22, L14_23, L15_24, L16_25, L17_26, L18_27, L19_28, L20_29, L21_30, L22_31, L23_32, L24_33
  L0_9 = GetComponent
  L1_10 = __this__
  L2_11 = "HazingObjectDescriptor"
  L0_9 = L0_9(L1_10, L2_11)
  L2_11 = L0_9
  L1_10 = L0_9.GetObjectDescriptor
  L1_10 = L1_10(L2_11)
  L2_11 = L1_10
  L1_10 = L1_10.GetStateAttributes
  L1_10 = L1_10(L2_11)
  L2_11 = FetchHashedStringFromDatabase
  L3_12 = L1_10
  L4_13 = "__hash_0x2a219ed9"
  L2_11 = L2_11(L3_12, L4_13)
  gDesiredActionTypeVar = L2_11
  L2_11 = FetchHashedStringFromDatabase
  L3_12 = L1_10
  L4_13 = "__hash_0xd795d55e"
  L2_11 = L2_11(L3_12, L4_13)
  gDesiredActionSubTypeVar = L2_11
  L2_11 = FetchHashedStringFromDatabase
  L3_12 = L1_10
  L4_13 = "__hash_0x6af5c022"
  L2_11 = L2_11(L3_12, L4_13)
  gCurrentActionTypeVar = L2_11
  L2_11 = FetchHashedStringFromDatabase
  L3_12 = L1_10
  L4_13 = "__hash_0xcb822f38"
  L2_11 = L2_11(L3_12, L4_13)
  gCurrentActionSubTypeVar = L2_11
  L2_11 = FetchVectorFromDatabase
  L3_12 = L1_10
  L4_13 = "__hash_0x3e4ad1b3"
  L2_11 = L2_11(L3_12, L4_13)
  gDirectionVar = L2_11
  L2_11 = FetchVectorFromDatabase
  L3_12 = L1_10
  L4_13 = "__hash_0xcbda696f"
  L2_11 = L2_11(L3_12, L4_13)
  gAttackPositionVar = L2_11
  L2_11 = FetchFloatFromDatabase
  L3_12 = L1_10
  L4_13 = "__hash_0x0f26fef6"
  L2_11 = L2_11(L3_12, L4_13)
  gSpeedVar = L2_11
  L2_11 = FetchFloatFromDatabase
  L3_12 = L1_10
  L4_13 = "__hash_0x865f80c0"
  L2_11 = L2_11(L3_12, L4_13)
  gDurationVar = L2_11
  L2_11 = FetchBoolFromDatabase
  L3_12 = L1_10
  L4_13 = "__hash_0xd3098bfb"
  L2_11 = L2_11(L3_12, L4_13)
  gDyingVar = L2_11
  L2_11 = FetchBoolFromDatabase
  L3_12 = L1_10
  L4_13 = "__hash_0xed254924"
  L2_11 = L2_11(L3_12, L4_13)
  gDeadVar = L2_11
  L2_11 = FetchBoolFromDatabase
  L3_12 = L1_10
  L4_13 = "__hash_0x60e3af4e"
  L2_11 = L2_11(L3_12, L4_13)
  gWaitingRespawnVar = L2_11
  L2_11 = FetchBoolFromDatabase
  L3_12 = L1_10
  L4_13 = "__hash_0x0b7c5057"
  L2_11 = L2_11(L3_12, L4_13)
  gBodyHurtVar = L2_11
  L2_11 = FetchBoolFromDatabase
  L3_12 = L1_10
  L4_13 = "__hash_0x8bcd3db0"
  L2_11 = L2_11(L3_12, L4_13)
  gCanBeInterruptedByAdditive = L2_11
  L2_11 = FetchBoolFromDatabase
  L3_12 = L1_10
  L4_13 = "__hash_0x5cb7cbfc"
  L2_11 = L2_11(L3_12, L4_13)
  gAdditiveHurtVar = L2_11
  L2_11 = FetchBoolFromDatabase
  L3_12 = L1_10
  L4_13 = "__hash_0xa477e2c4"
  L2_11 = L2_11(L3_12, L4_13)
  gNewBodyHurtVar = L2_11
  L2_11 = FetchHashedStringFromDatabase
  L3_12 = L1_10
  L4_13 = "__hash_0x49959282"
  L2_11 = L2_11(L3_12, L4_13)
  gBodyHurtAnimVar = L2_11
  L2_11 = FetchBoolFromDatabase
  L3_12 = L1_10
  L4_13 = "__hash_0xf0e8c905"
  L2_11 = L2_11(L3_12, L4_13)
  gLockOnVar = L2_11
  L2_11 = FetchBoolFromDatabase
  L3_12 = L1_10
  L4_13 = "__hash_0x95b19108"
  L2_11 = L2_11(L3_12, L4_13)
  gStuckInTrapVar = L2_11
  L2_11 = FetchBoolFromDatabase
  L3_12 = L1_10
  L4_13 = "__hash_0x6221037e"
  L2_11 = L2_11(L3_12, L4_13)
  gStuntVar = L2_11
  L2_11 = FetchBoolFromDatabase
  L3_12 = L1_10
  L4_13 = "__hash_0x6c11c33d"
  L2_11 = L2_11(L3_12, L4_13)
  gChargeHitStuntVar = L2_11
  L2_11 = FetchBoolFromDatabase
  L3_12 = L1_10
  L4_13 = "__hash_0x9644a17f"
  L2_11 = L2_11(L3_12, L4_13)
  gQuestionThreatVar = L2_11
  L2_11 = FetchBoolFromDatabase
  L3_12 = L1_10
  L4_13 = "__hash_0x2df8175b"
  L2_11 = L2_11(L3_12, L4_13)
  gGreetVar = L2_11
  L2_11 = FetchHashedStringFromDatabase
  L3_12 = L1_10
  L4_13 = "__hash_0x81a177a1"
  L2_11 = L2_11(L3_12, L4_13)
  gGreetTargetVar = L2_11
  L2_11 = FetchBoolFromDatabase
  L3_12 = L1_10
  L4_13 = "__hash_0xe7a46c8d"
  L2_11 = L2_11(L3_12, L4_13)
  gUnderCoverVar = L2_11
  L2_11 = FetchBoolFromDatabase
  L3_12 = L1_10
  L4_13 = "__hash_0xd79b1dcd"
  L2_11 = L2_11(L3_12, L4_13)
  gCarryingBody = L2_11
  L2_11 = FetchBoolFromDatabase
  L3_12 = L1_10
  L4_13 = "__hash_0x24877071"
  L2_11 = L2_11(L3_12, L4_13)
  gTouching = L2_11
  L2_11 = FetchBoolFromDatabase
  L3_12 = L1_10
  L4_13 = "__hash_0x8a636522"
  L2_11 = L2_11(L3_12, L4_13)
  gKnockedDown = L2_11
  L2_11 = FetchBoolFromDatabase
  L3_12 = L1_10
  L4_13 = "__hash_0x885de9bd"
  L2_11 = L2_11(L3_12, L4_13)
  gHidden = L2_11
  L2_11 = FetchBoolFromDatabase
  L3_12 = L1_10
  L4_13 = "__hash_0x40aa05c3"
  L2_11 = L2_11(L3_12, L4_13)
  gAiming = L2_11
  L2_11 = FetchBoolFromDatabase
  L3_12 = L1_10
  L4_13 = "__hash_0x96e727ba"
  L2_11 = L2_11(L3_12, L4_13)
  gTaunting = L2_11
  L2_11 = FetchBoolFromDatabase
  L3_12 = L1_10
  L4_13 = "__hash_0xa4064e9c"
  L2_11 = L2_11(L3_12, L4_13)
  gIsWaitingForCallVar = L2_11
  L2_11 = Bool
  L3_12 = "__hash_0x97255620"  -- questionThreatStateRunning
  L4_13 = false
  L2_11 = L2_11(L3_12, L4_13)
  questionThreatStateRunning = L2_11
  L2_11 = GetComponent
  L3_12 = __this__
  L4_13 = "StateSelector"
  L2_11 = L2_11(L3_12, L4_13)
  L3_12 = engine
  L3_12 = L3_12.StateSelectorProxy
  L3_12 = L3_12()
  baseCharacterBodyStateSelector = L3_12
  L4_13 = L2_11
  L3_12 = L2_11.Create
  L5_14 = "__hash_0xdba80bb2"
  L6_15 = baseCharacterBodyStateSelector
  L3_12(L4_13, L5_14, L6_15)
  L3_12 = Equal
  L4_13 = gDyingVar
  L5_14 = true
  L3_12 = L3_12(L4_13, L5_14)
  gConditionDying = L3_12
  L3_12 = Equal
  L4_13 = gWaitingRespawnVar
  L5_14 = true
  L3_12 = L3_12(L4_13, L5_14)
  gConditionWaitingToRespawn = L3_12
  L3_12 = Equal
  L4_13 = gDeadVar
  L5_14 = true
  L3_12 = L3_12(L4_13, L5_14)
  gConditionDead = L3_12
  L3_12 = And
  L4_13 = Not
  L5_14 = gConditionDead
  L4_13 = L4_13(L5_14)
  L5_14 = Not
  L6_15 = gConditionDying
  L5_14 = L5_14(L6_15)
  L6_15 = Not
  L7_16 = gConditionWaitingToRespawn
  L24_33 = L6_15(L7_16)
  L3_12 = L3_12(L4_13, L5_14, L6_15, L7_16, L8_17, L9_18, L10_19, L11_20, L12_21, L13_22, L14_23, L15_24, L16_25, L17_26, L18_27, L19_28, L20_29, L21_30, L22_31, L23_32, L24_33, L6_15(L7_16))
  gConditionNotDead = L3_12
  L3_12 = Equal
  L4_13 = gCanBeInterruptedByAdditive
  L5_14 = true
  L3_12 = L3_12(L4_13, L5_14)
  gConditionCanBeInterruptedByAdditive = L3_12
  L3_12 = Equal
  L4_13 = gAdditiveHurtVar
  L5_14 = true
  L3_12 = L3_12(L4_13, L5_14)
  gConditionHurtLongDistance = L3_12
  L3_12 = Equal
  L4_13 = gBodyHurtVar
  L5_14 = true
  L3_12 = L3_12(L4_13, L5_14)
  gConditionHurt = L3_12
  L3_12 = Not
  L4_13 = gConditionHurt
  L3_12 = L3_12(L4_13)
  gConditionNotHurt = L3_12
  L3_12 = Equal
  L4_13 = gStuckInTrapVar
  L5_14 = true
  L3_12 = L3_12(L4_13, L5_14)
  gConditionStuckInTrap = L3_12
  L3_12 = Not
  L4_13 = gConditionStuckInTrap
  L3_12 = L3_12(L4_13)
  gConditionNotStuckInTrap = L3_12
  L3_12 = Equal
  L4_13 = gStuntVar
  L5_14 = true
  L3_12 = L3_12(L4_13, L5_14)
  gConditionStunt = L3_12
  L3_12 = Not
  L4_13 = gConditionStunt
  L3_12 = L3_12(L4_13)
  gConditionNotStunt = L3_12
  L3_12 = Equal
  L4_13 = gChargeHitStuntVar
  L5_14 = true
  L3_12 = L3_12(L4_13, L5_14)
  gConditionChargeHitStunt = L3_12
  L3_12 = Not
  L4_13 = gConditionChargeHitStunt
  L3_12 = L3_12(L4_13)
  gConditionNotChargeHitStunt = L3_12
  L3_12 = Equal
  L4_13 = gCarryingBody
  L5_14 = true
  L3_12 = L3_12(L4_13, L5_14)
  gConditionCarryingBody = L3_12
  L3_12 = Not
  L4_13 = gConditionCarryingBody
  L3_12 = L3_12(L4_13)
  gConditionNotCarryingBody = L3_12
  L3_12 = Equal
  L4_13 = gQuestionThreatVar
  L5_14 = true
  L3_12 = L3_12(L4_13, L5_14)
  gConditionQuestionThreat = L3_12
  L3_12 = Not
  L4_13 = gConditionQuestionThreat
  L3_12 = L3_12(L4_13)
  gConditionNotQuestionThreat = L3_12
  L3_12 = Equal
  L4_13 = gHidden
  L5_14 = true
  L3_12 = L3_12(L4_13, L5_14)
  gConditionHidden = L3_12
  L3_12 = Not
  L4_13 = gConditionHidden
  L3_12 = L3_12(L4_13)
  gConditionNotHidden = L3_12
  L3_12 = Equal
  L4_13 = gAiming
  L5_14 = true
  L3_12 = L3_12(L4_13, L5_14)
  gConditionAiming = L3_12
  L3_12 = Equal
  L4_13 = gKnockedDown
  L5_14 = true
  L3_12 = L3_12(L4_13, L5_14)
  gConditionKnockedDown = L3_12
  L3_12 = Not
  L4_13 = gConditionKnockedDown
  L3_12 = L3_12(L4_13)
  gConditionNotKnockedDown = L3_12
  L3_12 = Equal
  L4_13 = gDesiredActionTypeVar
  L5_14 = "KnockedDownOut"
  L3_12 = L3_12(L4_13, L5_14)
  gDesiredActionKnockedDownOut = L3_12
  L3_12 = Equal
  L4_13 = gTaunting
  L5_14 = true
  L3_12 = L3_12(L4_13, L5_14)
  gConditionTaunting = L3_12
  L3_12 = And
  L4_13 = And
  L5_14 = gConditionNotHurt
  L6_15 = gConditionNotDead
  L4_13 = L4_13(L5_14, L6_15)
  L5_14 = And
  L6_15 = gConditionNotStunt
  L7_16 = gConditionNotChargeHitStunt
  L24_33 = L5_14(L6_15, L7_16)
  L3_12 = L3_12(L4_13, L5_14, L6_15, L7_16, L8_17, L9_18, L10_19, L11_20, L12_21, L13_22, L14_23, L15_24, L16_25, L17_26, L18_27, L19_28, L20_29, L21_30, L22_31, L23_32, L24_33, L5_14(L6_15, L7_16))
  gConditionUnharmedNoTrap = L3_12
  L3_12 = And
  L4_13 = gConditionUnharmedNoTrap
  L5_14 = gConditionNotStuckInTrap
  L3_12 = L3_12(L4_13, L5_14)
  gConditionUnharmed = L3_12
  L3_12 = Equal
  L4_13 = gDesiredActionTypeVar
  L5_14 = "Idle"
  L3_12 = L3_12(L4_13, L5_14)
  gDesiredActionIdle = L3_12
  L3_12 = Equal
  L4_13 = gDesiredActionTypeVar
  L5_14 = "Aim"
  L3_12 = L3_12(L4_13, L5_14)
  gDesiredActionAim = L3_12
  L3_12 = Equal
  L4_13 = gDesiredActionTypeVar
  L5_14 = "Walk"
  L3_12 = L3_12(L4_13, L5_14)
  gDesiredActionWalk = L3_12
  L3_12 = Equal
  L4_13 = gDesiredActionTypeVar
  L5_14 = "Run"
  L3_12 = L3_12(L4_13, L5_14)
  gDesiredActionRun = L3_12
  L3_12 = Equal
  L4_13 = gCurrentActionTypeVar
  L5_14 = "Run"
  L3_12 = L3_12(L4_13, L5_14)
  gCurrentActionRun = L3_12
  L3_12 = Equal
  L4_13 = gDesiredActionTypeVar
  L5_14 = "Sprint"
  L3_12 = L3_12(L4_13, L5_14)
  gDesiredActionSprint = L3_12
  L3_12 = Equal
  L4_13 = gCurrentActionTypeVar
  L5_14 = "Sprint"
  L3_12 = L3_12(L4_13, L5_14)
  gCurrentActionSprint = L3_12
  L3_12 = Equal
  L4_13 = gDesiredActionTypeVar
  L5_14 = "StrafeLeft"
  L3_12 = L3_12(L4_13, L5_14)
  gDesiredActionStrafeLeft = L3_12
  L3_12 = Equal
  L4_13 = gDesiredActionTypeVar
  L5_14 = "StrafeRight"
  L3_12 = L3_12(L4_13, L5_14)
  gDesiredActionStrafeRight = L3_12
  L3_12 = Equal
  L4_13 = gDesiredActionTypeVar
  L5_14 = "WalkBack"
  L3_12 = L3_12(L4_13, L5_14)
  gDesiredActionWalkBack = L3_12
  L3_12 = Equal
  L4_13 = gDesiredActionTypeVar
  L5_14 = "Dodge"
  L3_12 = L3_12(L4_13, L5_14)
  gDesiredActionDodge = L3_12
  L3_12 = Equal
  L4_13 = gDesiredActionTypeVar
  L5_14 = "JumpSide"
  L3_12 = L3_12(L4_13, L5_14)
  gDesiredActionJumpSide = L3_12
  L3_12 = Equal
  L4_13 = gDesiredActionTypeVar
  L5_14 = "Counter"
  L3_12 = L3_12(L4_13, L5_14)
  gDesiredActionCounter = L3_12
  L3_12 = Equal
  L4_13 = gDesiredActionTypeVar
  L5_14 = "Block"
  L3_12 = L3_12(L4_13, L5_14)
  gDesiredActionBlock = L3_12
  L3_12 = Equal
  L4_13 = gDesiredActionTypeVar
  L5_14 = "BlockStop"
  L3_12 = L3_12(L4_13, L5_14)
  gDesiredActionBlockStop = L3_12
  L3_12 = Equal
  L4_13 = gDesiredActionTypeVar
  L5_14 = "Generic"
  L3_12 = L3_12(L4_13, L5_14)
  gDesiredActionGeneric = L3_12
  L3_12 = Equal
  L4_13 = gDesiredActionTypeVar
  L5_14 = "DoStealthKill"
  L3_12 = L3_12(L4_13, L5_14)
  gDesiredActionDoStealthKill = L3_12
  L3_12 = Equal
  L4_13 = gDesiredActionTypeVar
  L5_14 = "ReceiveStealthKill"
  L3_12 = L3_12(L4_13, L5_14)
  gDesiredActionReceiveStealthKill = L3_12
  L3_12 = Equal
  L4_13 = gDesiredActionTypeVar
  L5_14 = "DoScareAttack"
  L3_12 = L3_12(L4_13, L5_14)
  gDesiredActionDoScareAttack = L3_12
  L3_12 = Equal
  L4_13 = gDesiredActionTypeVar
  L5_14 = "ReceiveScareAttack"
  L3_12 = L3_12(L4_13, L5_14)
  gDesiredActionReceiveScareAttack = L3_12
  L3_12 = Equal
  L4_13 = gDesiredActionTypeVar
  L5_14 = "ReceiveQuestionThreat"
  L3_12 = L3_12(L4_13, L5_14)
  gDesiredActionReceiveQuestionThreat = L3_12
  L3_12 = Equal
  L4_13 = gDesiredActionTypeVar
  L5_14 = "Taunt"
  L3_12 = L3_12(L4_13, L5_14)
  gDesiredActionTaunt = L3_12
  L3_12 = Equal
  L4_13 = gDesiredActionTypeVar
  L5_14 = "Attack"
  L3_12 = L3_12(L4_13, L5_14)
  gDesiredActionAttack = L3_12
  L3_12 = Equal
  L4_13 = gDesiredActionSubTypeVar
  L5_14 = "DodgeAttack01"
  L3_12 = L3_12(L4_13, L5_14)
  gDesiredSubActionDodgeAttack01 = L3_12
  L3_12 = Equal
  L4_13 = gDesiredActionTypeVar
  L5_14 = "Shoot"
  L3_12 = L3_12(L4_13, L5_14)
  gDesiredActionShoot = L3_12
  L3_12 = Equal
  L4_13 = gDesiredActionTypeVar
  L5_14 = "Reload"
  L3_12 = L3_12(L4_13, L5_14)
  gDesiredActionReload = L3_12
  L3_12 = Equal
  L4_13 = gDesiredActionTypeVar
  L5_14 = "Terrorize"
  L3_12 = L3_12(L4_13, L5_14)
  gDesiredActionTerrorize = L3_12
  L3_12 = Equal
  L4_13 = gDesiredActionTypeVar
  L5_14 = "ChargeAttack"
  L3_12 = L3_12(L4_13, L5_14)
  gDesiredActionChargeAttack = L3_12
  L3_12 = Equal
  L4_13 = gDesiredActionTypeVar
  L5_14 = "DoSynchronizeAction"
  L3_12 = L3_12(L4_13, L5_14)
  gDesiredActionDoSyncAction = L3_12
  L3_12 = Equal
  L4_13 = gDesiredActionTypeVar
  L5_14 = "ReceiveSynchronizeAction"
  L3_12 = L3_12(L4_13, L5_14)
  gDesiredActionReceiveSyncAction = L3_12
  L3_12 = Equal
  L4_13 = gDesiredActionTypeVar
  L5_14 = "EndGame"
  L3_12 = L3_12(L4_13, L5_14)
  gDesiredActionEndGame = L3_12
  L3_12 = Equal
  L4_13 = gLockOnVar
  L5_14 = true
  L3_12 = L3_12(L4_13, L5_14)
  gConditionLockOn = L3_12
  L3_12 = Or
  L4_13 = gConditionAiming
  L5_14 = gConditionLockOn
  L3_12 = L3_12(L4_13, L5_14)
  gconditionLockOrAim = L3_12
  L3_12 = Equal
  L4_13 = gDesiredActionTypeVar
  L5_14 = "Interact"
  L3_12 = L3_12(L4_13, L5_14)
  gDesiredActionDeprecatedInteract = L3_12
  L3_12 = Equal
  L4_13 = gDesiredActionTypeVar
  L5_14 = "MultiInteract"
  L3_12 = L3_12(L4_13, L5_14)
  gDesiredActionInteract = L3_12
  L3_12 = Bool
  L4_13 = "__hash_0x4dbf0fb6"  -- stateChangeAllowed
  L5_14 = true
  L3_12 = L3_12(L4_13, L5_14)
  stateChangeAllowed = L3_12
  L3_12 = Equal
  L4_13 = stateChangeAllowed
  L5_14 = true
  L3_12 = L3_12(L4_13, L5_14)
  conditionStateChangeAllowed = L3_12
  L3_12 = Bool
  L4_13 = "__hash_0x5b996336"  -- transitionToSyncActionAllowed
  L5_14 = false
  L3_12 = L3_12(L4_13, L5_14)
  transitionToSyncActionAllowed = L3_12
  L3_12 = Equal
  L4_13 = transitionToSyncActionAllowed
  L5_14 = true
  L3_12 = L3_12(L4_13, L5_14)
  conditionTransitionToSyncActionAllowed = L3_12
  L3_12 = Bool
  L4_13 = "__hash_0x9c5cc24b"
  L5_14 = false
  L3_12 = L3_12(L4_13, L5_14)
  gTransitionToBlockStateAllowed = L3_12
  L3_12 = Equal
  L4_13 = gTransitionToBlockStateAllowed
  L5_14 = true
  L3_12 = L3_12(L4_13, L5_14)
  gConditionTransitionToBlockStateAllowed = L3_12
  L3_12 = Bool
  L4_13 = "__hash_0x5a05b963"
  L5_14 = false
  L3_12 = L3_12(L4_13, L5_14)
  gTransitionToDodgeStateAllowed = L3_12
  L3_12 = Equal
  L4_13 = gTransitionToDodgeStateAllowed
  L5_14 = true
  L3_12 = L3_12(L4_13, L5_14)
  gConditionTransitionToDodgeStateAllowed = L3_12
  L3_12 = Bool
  L4_13 = "__hash_0x58c9d1b4"
  L5_14 = false
  L3_12 = L3_12(L4_13, L5_14)
  gIsTerrorizing = L3_12
  L3_12 = Equal
  L4_13 = gIsTerrorizing
  L5_14 = true
  L3_12 = L3_12(L4_13, L5_14)
  gConditionIsTerrorizing = L3_12
  L3_12 = Bool
  L4_13 = "__hash_0x96f03f89"  -- stateLocalNavigationForInteract
  L5_14 = false
  L3_12 = L3_12(L4_13, L5_14)
  stateLocalNavigationForInteract = L3_12
  L3_12 = Equal
  L4_13 = stateLocalNavigationForInteract
  L5_14 = true
  L3_12 = L3_12(L4_13, L5_14)
  gConditionLocalNavigationForInteract = L3_12
  L3_12 = Bool
  L4_13 = "__hash_0xd0992889"
  L5_14 = false
  L3_12 = L3_12(L4_13, L5_14)
  forceRespawnState = L3_12
  L3_12 = Equal
  L4_13 = forceRespawnState
  L5_14 = true
  L3_12 = L3_12(L4_13, L5_14)
  L4_13 = CreateState
  L5_14 = L3_12
  L6_15 = "__hash_0x90b4dad0"  -- stateForceRespawn
  L4_13 = L4_13(L5_14, L6_15)
  stateForceRespawn = L4_13
  L4_13 = stateForceRespawn
  L5_14 = L4_13
  L4_13 = L4_13.SetCallbacks
  L6_15 = "StateRespawn_Enter"
  L7_16 = "StateRespawn_Exit"
  L4_13(L5_14, L6_15, L7_16)
  L4_13 = baseCharacterBodyStateSelector
  L5_14 = L4_13
  L4_13 = L4_13.Register
  L6_15 = stateForceRespawn
  L4_13(L5_14, L6_15)
  L4_13 = And
  L5_14 = gConditionUnharmed
  L6_15 = conditionStateChangeAllowed
  L4_13 = L4_13(L5_14, L6_15)
  commonConditionAttack = L4_13
  L4_13 = Bool
  L5_14 = "__hash_0x352981f6"  -- attackStateRunning
  L6_15 = false
  L4_13 = L4_13(L5_14, L6_15)
  attackStateRunning = L4_13
  L4_13 = Equal
  L5_14 = attackStateRunning
  L6_15 = true
  L4_13 = L4_13(L5_14, L6_15)
  L5_14 = And
  L6_15 = Or
  L7_16 = gDesiredActionAttack
  L8_17 = L4_13
  L6_15 = L6_15(L7_16, L8_17)
  L7_16 = commonConditionAttack
  L5_14 = L5_14(L6_15, L7_16)
  conditionAttack = L5_14
  L5_14 = CreateState
  L6_15 = conditionAttack
  L7_16 = "__hash_0xbf6b45ab"  -- stateAttack
  L5_14 = L5_14(L6_15, L7_16)
  stateAttack = L5_14
  L5_14 = stateAttack
  L6_15 = L5_14
  L5_14 = L5_14.SetCallbacks
  L7_16 = "StateAttack_Enter"
  L8_17 = "StateAttack_Exit"
  L5_14(L6_15, L7_16, L8_17)
  L5_14 = baseCharacterBodyStateSelector
  L6_15 = L5_14
  L5_14 = L5_14.Register
  L7_16 = stateAttack
  L5_14(L6_15, L7_16)
  L5_14 = Bool
  L6_15 = "__hash_0xdfa2fa8e"  -- reloadStateRunning
  L7_16 = false
  L5_14 = L5_14(L6_15, L7_16)
  reloadStateRunning = L5_14
  L5_14 = Equal
  L6_15 = reloadStateRunning
  L7_16 = true
  L5_14 = L5_14(L6_15, L7_16)
  L6_15 = And
  L7_16 = Or
  L8_17 = gDesiredActionReload
  L9_18 = L5_14
  L7_16 = L7_16(L8_17, L9_18)
  L8_17 = commonConditionAttack
  L6_15 = L6_15(L7_16, L8_17)
  conditionReload = L6_15
  L6_15 = CreateState
  L7_16 = conditionReload
  L8_17 = "__hash_0x5a13a6c5"  -- stateReload
  L6_15 = L6_15(L7_16, L8_17)
  stateReload = L6_15
  L6_15 = stateReload
  L7_16 = L6_15
  L6_15 = L6_15.SetCallbacks
  L8_17 = "StateReload_Enter"
  L9_18 = "StateReload_Exit"
  L6_15(L7_16, L8_17, L9_18)
  L6_15 = baseCharacterBodyStateSelector
  L7_16 = L6_15
  L6_15 = L6_15.Register
  L8_17 = stateReload
  L6_15(L7_16, L8_17)
  L6_15 = Bool
  L7_16 = "__hash_0x74c79086"  -- chargeAttackStateRunning
  L8_17 = false
  L6_15 = L6_15(L7_16, L8_17)
  chargeAttackStateRunning = L6_15
  L6_15 = Equal
  L7_16 = chargeAttackStateRunning
  L8_17 = true
  L6_15 = L6_15(L7_16, L8_17)
  L7_16 = And
  L8_17 = Or
  L9_18 = gDesiredActionChargeAttack
  L10_19 = L6_15
  L8_17 = L8_17(L9_18, L10_19)
  L9_18 = commonConditionAttack
  L7_16 = L7_16(L8_17, L9_18)
  conditionChargeAttack = L7_16
  L7_16 = CreateState
  L8_17 = conditionChargeAttack
  L9_18 = "__hash_0x4e455b2c"  -- stateChargeAttack
  L7_16 = L7_16(L8_17, L9_18)
  stateChargeAttack = L7_16
  L7_16 = stateChargeAttack
  L8_17 = L7_16
  L7_16 = L7_16.SetCallbacks
  L9_18 = "StateChargeAttack_Enter"
  L10_19 = "StateChargeAttack_Exit"
  L7_16(L8_17, L9_18, L10_19)
  L7_16 = baseCharacterBodyStateSelector
  L8_17 = L7_16
  L7_16 = L7_16.Register
  L9_18 = stateChargeAttack
  L7_16(L8_17, L9_18)
  L7_16 = And
  L8_17 = And
  L9_18 = And
  L10_19 = gConditionUnharmed
  L11_20 = gDesiredActionIdle
  L9_18 = L9_18(L10_19, L11_20)
  L10_19 = gConditionLockOn
  L8_17 = L8_17(L9_18, L10_19)
  L9_18 = conditionStateChangeAllowed
  L7_16 = L7_16(L8_17, L9_18)
  L8_17 = CreateState
  L9_18 = L7_16
  L10_19 = "__hash_0x0843a195"  -- stateLockOn
  L8_17 = L8_17(L9_18, L10_19)
  stateLockOn = L8_17
  L8_17 = stateLockOn
  L9_18 = L8_17
  L8_17 = L8_17.SetCallbacks
  L10_19 = "StateLockOn_Enter"
  L11_20 = "StateLockOn_Exit"
  L8_17(L9_18, L10_19, L11_20)
  L8_17 = baseCharacterBodyStateSelector
  L9_18 = L8_17
  L8_17 = L8_17.Register
  L10_19 = stateLockOn
  L8_17(L9_18, L10_19)
  L8_17 = engine
  L8_17 = L8_17.ScriptableVariableObserver
  L9_18 = GetScriptComponent
  L10_19 = __this__
  L9_18 = L9_18(L10_19)
  L10_19 = gLockOnVar
  L11_20 = L10_19
  L10_19 = L10_19.UpCastToVariableProxy
  L24_33 = L10_19(L11_20)
  L8_17 = L8_17(L9_18, L10_19, L11_20, L12_21, L13_22, L14_23, L15_24, L16_25, L17_26, L18_27, L19_28, L20_29, L21_30, L22_31, L23_32, L24_33, L10_19(L11_20))
  baseCharacterLockOnObserver = L8_17
  L8_17 = baseCharacterLockOnObserver
  L9_18 = L8_17
  L8_17 = L8_17.SetCallback
  L10_19 = "lockOnValueChange"
  L8_17(L9_18, L10_19)
  L8_17 = And
  L9_18 = And
  L10_19 = gConditionUnharmed
  L11_20 = gDesiredActionJumpSide
  L9_18 = L9_18(L10_19, L11_20)
  L10_19 = conditionStateChangeAllowed
  L8_17 = L8_17(L9_18, L10_19)
  L9_18 = CreateState
  L10_19 = L8_17
  L11_20 = "__hash_0xe70c3faf"  -- stateJumpSide
  L9_18 = L9_18(L10_19, L11_20)
  stateJumpSide = L9_18
  L9_18 = stateJumpSide
  L10_19 = L9_18
  L9_18 = L9_18.SetCallbacks
  L11_20 = "StateJumpSide_Enter"
  L12_21 = "StateJumpSide_Exit"
  L9_18(L10_19, L11_20, L12_21)
  L9_18 = baseCharacterBodyStateSelector
  L10_19 = L9_18
  L9_18 = L9_18.Register
  L11_20 = stateJumpSide
  L9_18(L10_19, L11_20)
  L9_18 = And
  L10_19 = And
  L11_20 = gConditionUnharmed
  L12_21 = gDesiredActionCounter
  L10_19 = L10_19(L11_20, L12_21)
  L11_20 = conditionStateChangeAllowed
  L9_18 = L9_18(L10_19, L11_20)
  L10_19 = CreateState
  L11_20 = L9_18
  L12_21 = "__hash_0x31d5ac54"  -- stateCounter
  L10_19 = L10_19(L11_20, L12_21)
  stateCounter = L10_19
  L10_19 = stateCounter
  L11_20 = L10_19
  L10_19 = L10_19.SetCallbacks
  L12_21 = "StateCounter_Enter"
  L13_22 = "StateCounter_Exit"
  L10_19(L11_20, L12_21, L13_22)
  L10_19 = baseCharacterBodyStateSelector
  L11_20 = L10_19
  L10_19 = L10_19.Register
  L12_21 = stateCounter
  L10_19(L11_20, L12_21)
  L10_19 = Bool
  L11_20 = "__hash_0x5cfc5722"  -- doStealthKillStateRunning
  L12_21 = false
  L10_19 = L10_19(L11_20, L12_21)
  doStealthKillStateRunning = L10_19
  L10_19 = Equal
  L11_20 = doStealthKillStateRunning
  L12_21 = true
  L10_19 = L10_19(L11_20, L12_21)
  conditionDoStealthKillStateRunning = L10_19
  L10_19 = Bool
  L11_20 = "__hash_0xa2de4969"  -- receiveStealthKillStateRunning
  L12_21 = false
  L10_19 = L10_19(L11_20, L12_21)
  receiveStealthKillStateRunning = L10_19
  L10_19 = Equal
  L11_20 = receiveStealthKillStateRunning
  L12_21 = true
  L10_19 = L10_19(L11_20, L12_21)
  conditionReceiveStealthKillStateRunning = L10_19
  L10_19 = Bool
  L11_20 = "__hash_0xd7b4b7f4"  -- doScareAttackStateRunning
  L12_21 = false
  L10_19 = L10_19(L11_20, L12_21)
  doScareAttackStateRunning = L10_19
  L10_19 = Equal
  L11_20 = doScareAttackStateRunning
  L12_21 = true
  L10_19 = L10_19(L11_20, L12_21)
  conditionDoScareAttackStateRunning = L10_19
  L10_19 = Bool
  L11_20 = "__hash_0x2996a9bf"  -- receiveScareAttackStateRunning
  L12_21 = false
  L10_19 = L10_19(L11_20, L12_21)
  receiveScareAttackStateRunning = L10_19
  L10_19 = Equal
  L11_20 = receiveScareAttackStateRunning
  L12_21 = true
  L10_19 = L10_19(L11_20, L12_21)
  conditionReceiveScareAttackStateRunning = L10_19
  L10_19 = Bool
  L11_20 = "__hash_0x40ddda63"  -- doSyncActionStateRunning
  L12_21 = false
  L10_19 = L10_19(L11_20, L12_21)
  doSyncActionStateRunning = L10_19
  L10_19 = Equal
  L11_20 = doSyncActionStateRunning
  L12_21 = true
  L10_19 = L10_19(L11_20, L12_21)
  conditionDoSyncActionStateRunning = L10_19
  L10_19 = And
  L11_20 = And
  L12_21 = Or
  L13_22 = gDesiredActionDoSyncAction
  L14_23 = conditionDoSyncActionStateRunning
  L12_21 = L12_21(L13_22, L14_23)
  L13_22 = gConditionNotDead
  L11_20 = L11_20(L12_21, L13_22)
  L12_21 = Or
  L13_22 = conditionStateChangeAllowed
  L14_23 = conditionTransitionToSyncActionAllowed
  L24_33 = L12_21(L13_22, L14_23)
  L10_19 = L10_19(L11_20, L12_21, L13_22, L14_23, L15_24, L16_25, L17_26, L18_27, L19_28, L20_29, L21_30, L22_31, L23_32, L24_33, L12_21(L13_22, L14_23))
  conditionDoSyncAction = L10_19
  L10_19 = CreateState
  L11_20 = conditionDoSyncAction
  L12_21 = "__hash_0xce7be790"  -- stateDoSyncAction
  L10_19 = L10_19(L11_20, L12_21)
  stateDoSyncAction = L10_19
  L10_19 = stateDoSyncAction
  L11_20 = L10_19
  L10_19 = L10_19.SetCallbacks
  L12_21 = "StateDoSyncAction_Enter"
  L13_22 = "StateDoSyncAction_Exit"
  L10_19(L11_20, L12_21, L13_22)
  L10_19 = baseCharacterBodyStateSelector
  L11_20 = L10_19
  L10_19 = L10_19.Register
  L12_21 = stateDoSyncAction
  L10_19(L11_20, L12_21)
  L10_19 = Bool
  L11_20 = "__hash_0xb6d8e7fb"  -- receiveSyncActionStateRunning
  L12_21 = false
  L10_19 = L10_19(L11_20, L12_21)
  receiveSyncActionStateRunning = L10_19
  L10_19 = Equal
  L11_20 = receiveSyncActionStateRunning
  L12_21 = true
  L10_19 = L10_19(L11_20, L12_21)
  conditionReceiveSyncActionStateRunning = L10_19
  L10_19 = And
  L11_20 = Or
  L12_21 = gDesiredActionReceiveSyncAction
  L13_22 = conditionReceiveSyncActionStateRunning
  L11_20 = L11_20(L12_21, L13_22)
  L12_21 = And
  L13_22 = Not
  L14_23 = conditionReceiveStealthKillStateRunning
  L13_22 = L13_22(L14_23)
  L14_23 = Not
  L15_24 = conditionReceiveScareAttackStateRunning
  L24_33 = L14_23(L15_24)
  L24_33 = L12_21(L13_22, L14_23, L15_24, L16_25, L17_26, L18_27, L19_28, L20_29, L21_30, L22_31, L23_32, L24_33, L14_23(L15_24))
  L10_19 = L10_19(L11_20, L12_21, L13_22, L14_23, L15_24, L16_25, L17_26, L18_27, L19_28, L20_29, L21_30, L22_31, L23_32, L24_33, L12_21(L13_22, L14_23, L15_24, L16_25, L17_26, L18_27, L19_28, L20_29, L21_30, L22_31, L23_32, L24_33, L14_23(L15_24)))
  conditionReceiveSyncAction = L10_19
  L10_19 = CreateState
  L11_20 = conditionReceiveSyncAction
  L12_21 = "__hash_0x9bc7db55"  -- stateReceiveSyncAction
  L10_19 = L10_19(L11_20, L12_21)
  stateReceiveSyncAction = L10_19
  L10_19 = stateReceiveSyncAction
  L11_20 = L10_19
  L10_19 = L10_19.SetCallbacks
  L12_21 = "StateReceiveSyncAction_Enter"
  L13_22 = "StateReceiveSyncAction_Exit"
  L10_19(L11_20, L12_21, L13_22)
  L10_19 = baseCharacterBodyStateSelector
  L11_20 = L10_19
  L10_19 = L10_19.Register
  L12_21 = stateReceiveSyncAction
  L10_19(L11_20, L12_21)
  L10_19 = Bool
  L11_20 = "__hash_0x64753fa9"  -- navigationStateRunning
  L12_21 = false
  L10_19 = L10_19(L11_20, L12_21)
  navigationStateRunning = L10_19
  L10_19 = Equal
  L11_20 = navigationStateRunning
  L12_21 = true
  L10_19 = L10_19(L11_20, L12_21)
  conditionNavigationStateRunning = L10_19
  L10_19 = Bool
  L11_20 = "__hash_0xefe631bf"  -- interactStateRunning
  L12_21 = false
  L10_19 = L10_19(L11_20, L12_21)
  interactStateRunning = L10_19
  L10_19 = Equal
  L11_20 = interactStateRunning
  L12_21 = true
  L10_19 = L10_19(L11_20, L12_21)
  conditionInteractStateRunning = L10_19
  L10_19 = Or
  L11_20 = gConditionLocalNavigationForInteract
  L12_21 = And
  L13_22 = Or
  L14_23 = gDesiredActionInteract
  L15_24 = Or
  L16_25 = conditionNavigationStateRunning
  L17_26 = conditionInteractStateRunning
  L24_33 = L15_24(L16_25, L17_26)
  L13_22 = L13_22(L14_23, L15_24, L16_25, L17_26, L18_27, L19_28, L20_29, L21_30, L22_31, L23_32, L24_33, L15_24(L16_25, L17_26))
  L14_23 = And
  L15_24 = conditionStateChangeAllowed
  L16_25 = gConditionUnharmed
  L24_33 = L14_23(L15_24, L16_25)
  L24_33 = L12_21(L13_22, L14_23, L15_24, L16_25, L17_26, L18_27, L19_28, L20_29, L21_30, L22_31, L23_32, L24_33, L14_23(L15_24, L16_25))
  L10_19 = L10_19(L11_20, L12_21, L13_22, L14_23, L15_24, L16_25, L17_26, L18_27, L19_28, L20_29, L21_30, L22_31, L23_32, L24_33, L12_21(L13_22, L14_23, L15_24, L16_25, L17_26, L18_27, L19_28, L20_29, L21_30, L22_31, L23_32, L24_33, L14_23(L15_24, L16_25)))
  conditionInteract = L10_19
  L10_19 = Or
  L11_20 = And
  L12_21 = gConditionHurtLongDistance
  L13_22 = gConditionCanBeInterruptedByAdditive
  L11_20 = L11_20(L12_21, L13_22)
  L12_21 = Not
  L13_22 = conditionInteractStateRunning
  L24_33 = L12_21(L13_22)
  L10_19 = L10_19(L11_20, L12_21, L13_22, L14_23, L15_24, L16_25, L17_26, L18_27, L19_28, L20_29, L21_30, L22_31, L23_32, L24_33, L12_21(L13_22))
  condShouldInterruptInteraction = L10_19
  L10_19 = CreateState
  L11_20 = conditionInteract
  L12_21 = "__hash_0x13dd3b31"  -- stateInteract
  L10_19 = L10_19(L11_20, L12_21)
  stateInteract = L10_19
  L10_19 = stateInteract
  L11_20 = L10_19
  L10_19 = L10_19.SetCallbacks
  L12_21 = "StateInteract_Enter"
  L13_22 = "StateInteract_Exit"
  L10_19(L11_20, L12_21, L13_22)
  L10_19 = baseCharacterBodyStateSelector
  L11_20 = L10_19
  L10_19 = L10_19.Register
  L12_21 = stateInteract
  L10_19(L11_20, L12_21)
  L10_19 = And
  L11_20 = Or
  L12_21 = gDesiredActionDoStealthKill
  L13_22 = conditionDoStealthKillStateRunning
  L11_20 = L11_20(L12_21, L13_22)
  L12_21 = And
  L13_22 = gConditionUnharmed
  L14_23 = conditionStateChangeAllowed
  L24_33 = L12_21(L13_22, L14_23)
  L10_19 = L10_19(L11_20, L12_21, L13_22, L14_23, L15_24, L16_25, L17_26, L18_27, L19_28, L20_29, L21_30, L22_31, L23_32, L24_33, L12_21(L13_22, L14_23))
  conditionDoStealthKill = L10_19
  L10_19 = CreateState
  L11_20 = conditionDoStealthKill
  L12_21 = "__hash_0xf3d65a51"
  L10_19 = L10_19(L11_20, L12_21)
  stateDoStealthKill = L10_19
  L10_19 = stateDoStealthKill
  L11_20 = L10_19
  L10_19 = L10_19.SetCallbacks
  L12_21 = "StateDoStealthKill_Enter"
  L13_22 = "StateDoStealthKill_Exit"
  L10_19(L11_20, L12_21, L13_22)
  L10_19 = baseCharacterBodyStateSelector
  L11_20 = L10_19
  L10_19 = L10_19.Register
  L12_21 = stateDoStealthKill
  L10_19(L11_20, L12_21)
  L10_19 = And
  L11_20 = Or
  L12_21 = gDesiredActionReceiveStealthKill
  L13_22 = conditionReceiveStealthKillStateRunning
  L11_20 = L11_20(L12_21, L13_22)
  L12_21 = And
  L13_22 = Not
  L14_23 = conditionReceiveScareAttackStateRunning
  L13_22 = L13_22(L14_23)
  L14_23 = Not
  L15_24 = conditionReceiveSyncActionStateRunning
  L24_33 = L14_23(L15_24)
  L24_33 = L12_21(L13_22, L14_23, L15_24, L16_25, L17_26, L18_27, L19_28, L20_29, L21_30, L22_31, L23_32, L24_33, L14_23(L15_24))
  L10_19 = L10_19(L11_20, L12_21, L13_22, L14_23, L15_24, L16_25, L17_26, L18_27, L19_28, L20_29, L21_30, L22_31, L23_32, L24_33, L12_21(L13_22, L14_23, L15_24, L16_25, L17_26, L18_27, L19_28, L20_29, L21_30, L22_31, L23_32, L24_33, L14_23(L15_24)))
  conditionReceiveStealthKill = L10_19
  L10_19 = CreateState
  L11_20 = conditionReceiveStealthKill
  L12_21 = "__hash_0x04ea2850"  -- ReceiveStealthKill
  L10_19 = L10_19(L11_20, L12_21)
  stateReceiveStealthKill = L10_19
  L10_19 = stateReceiveStealthKill
  L11_20 = L10_19
  L10_19 = L10_19.SetCallbacks
  L12_21 = "StateReceiveStealthKill_Enter"
  L13_22 = "StateReceiveStealthKill_Exit"
  L10_19(L11_20, L12_21, L13_22)
  L10_19 = baseCharacterBodyStateSelector
  L11_20 = L10_19
  L10_19 = L10_19.Register
  L12_21 = stateReceiveStealthKill
  L10_19(L11_20, L12_21)
  L10_19 = And
  L11_20 = Or
  L12_21 = gDesiredActionDoScareAttack
  L13_22 = conditionDoScareAttackStateRunning
  L11_20 = L11_20(L12_21, L13_22)
  L12_21 = And
  L13_22 = Or
  L14_23 = gConditionIsTerrorizing
  L15_24 = conditionStateChangeAllowed
  L13_22 = L13_22(L14_23, L15_24)
  L14_23 = gConditionUnharmed
  L24_33 = L12_21(L13_22, L14_23)
  L10_19 = L10_19(L11_20, L12_21, L13_22, L14_23, L15_24, L16_25, L17_26, L18_27, L19_28, L20_29, L21_30, L22_31, L23_32, L24_33, L12_21(L13_22, L14_23))
  conditionDoScareAttack = L10_19
  L10_19 = CreateState
  L11_20 = conditionDoScareAttack
  L12_21 = "__hash_0x034309a6"  -- stateDoScareAttack
  L10_19 = L10_19(L11_20, L12_21)
  stateDoScareAttack = L10_19
  L10_19 = stateDoScareAttack
  L11_20 = L10_19
  L10_19 = L10_19.SetCallbacks
  L12_21 = "StateDoScareAttack_Enter"
  L13_22 = "StateDoScareAttack_Exit"
  L10_19(L11_20, L12_21, L13_22)
  L10_19 = baseCharacterBodyStateSelector
  L11_20 = L10_19
  L10_19 = L10_19.Register
  L12_21 = stateDoScareAttack
  L10_19(L11_20, L12_21)
  L10_19 = And
  L11_20 = Or
  L12_21 = gDesiredActionReceiveScareAttack
  L13_22 = conditionReceiveScareAttackStateRunning
  L11_20 = L11_20(L12_21, L13_22)
  L12_21 = And
  L13_22 = Not
  L14_23 = conditionReceiveStealthKillStateRunning
  L13_22 = L13_22(L14_23)
  L14_23 = Not
  L15_24 = conditionReceiveSyncActionStateRunning
  L24_33 = L14_23(L15_24)
  L24_33 = L12_21(L13_22, L14_23, L15_24, L16_25, L17_26, L18_27, L19_28, L20_29, L21_30, L22_31, L23_32, L24_33, L14_23(L15_24))
  L10_19 = L10_19(L11_20, L12_21, L13_22, L14_23, L15_24, L16_25, L17_26, L18_27, L19_28, L20_29, L21_30, L22_31, L23_32, L24_33, L12_21(L13_22, L14_23, L15_24, L16_25, L17_26, L18_27, L19_28, L20_29, L21_30, L22_31, L23_32, L24_33, L14_23(L15_24)))
  conditionReceiveScareAttack = L10_19
  L10_19 = CreateState
  L11_20 = conditionReceiveScareAttack
  L12_21 = "__hash_0x1246e660"  -- ReceiveScareAttack
  L10_19 = L10_19(L11_20, L12_21)
  stateReceiveScareAttack = L10_19
  L10_19 = stateReceiveScareAttack
  L11_20 = L10_19
  L10_19 = L10_19.SetCallbacks
  L12_21 = "StateReceiveScareAttack_Enter"
  L13_22 = "StateReceiveScareAttack_Exit"
  L10_19(L11_20, L12_21, L13_22)
  L10_19 = baseCharacterBodyStateSelector
  L11_20 = L10_19
  L10_19 = L10_19.Register
  L12_21 = stateReceiveScareAttack
  L10_19(L11_20, L12_21)
  L10_19 = Bool
  L11_20 = "__hash_0xe82470c9"  -- dodgeStateRunning
  L12_21 = false
  L10_19 = L10_19(L11_20, L12_21)
  dodgeStateRunning = L10_19
  L10_19 = Equal
  L11_20 = dodgeStateRunning
  L12_21 = true
  L10_19 = L10_19(L11_20, L12_21)
  L11_20 = Not
  L12_21 = Or
  L13_22 = gDesiredActionReceiveScareAttack
  L14_23 = conditionReceiveScareAttackStateRunning
  L24_33 = L12_21(L13_22, L14_23)
  L11_20 = L11_20(L12_21, L13_22, L14_23, L15_24, L16_25, L17_26, L18_27, L19_28, L20_29, L21_30, L22_31, L23_32, L24_33, L12_21(L13_22, L14_23))
  L12_21 = And
  L13_22 = And
  L14_23 = Or
  L15_24 = gDesiredActionDodge
  L16_25 = L10_19
  L14_23 = L14_23(L15_24, L16_25)
  L15_24 = L11_20
  L13_22 = L13_22(L14_23, L15_24)
  L14_23 = Or
  L15_24 = And
  L16_25 = gConditionUnharmed
  L17_26 = And
  L18_27 = conditionStateChangeAllowed
  L19_28 = Not
  L20_29 = gDesiredSubActionDodgeAttack01
  L24_33 = L19_28(L20_29)
  L24_33 = L17_26(L18_27, L19_28, L20_29, L21_30, L22_31, L23_32, L24_33, L19_28(L20_29))
  L15_24 = L15_24(L16_25, L17_26, L18_27, L19_28, L20_29, L21_30, L22_31, L23_32, L24_33, L17_26(L18_27, L19_28, L20_29, L21_30, L22_31, L23_32, L24_33, L19_28(L20_29)))
  L16_25 = gConditionTransitionToDodgeStateAllowed
  L24_33 = L14_23(L15_24, L16_25)
  L12_21 = L12_21(L13_22, L14_23, L15_24, L16_25, L17_26, L18_27, L19_28, L20_29, L21_30, L22_31, L23_32, L24_33, L14_23(L15_24, L16_25))
  L13_22 = CreateState
  L14_23 = L12_21
  L15_24 = "__hash_0x58a93353"  -- stateDodge
  L13_22 = L13_22(L14_23, L15_24)
  stateDodge = L13_22
  L13_22 = stateDodge
  L14_23 = L13_22
  L13_22 = L13_22.SetCallbacks
  L15_24 = "StateDodge_Enter"
  L16_25 = "StateDodge_Exit"
  L13_22(L14_23, L15_24, L16_25)
  L13_22 = baseCharacterBodyStateSelector
  L14_23 = L13_22
  L13_22 = L13_22.Register
  L15_24 = stateDodge
  L13_22(L14_23, L15_24)
  L13_22 = Bool
  L14_23 = "__hash_0x5b665666"  -- blockStateRunning
  L15_24 = false
  L13_22 = L13_22(L14_23, L15_24)
  blockStateRunning = L13_22
  L13_22 = Equal
  L14_23 = blockStateRunning
  L15_24 = true
  L13_22 = L13_22(L14_23, L15_24)
  L14_23 = And
  L15_24 = And
  L16_25 = Or
  L17_26 = gDesiredActionBlock
  L18_27 = L13_22
  L16_25 = L16_25(L17_26, L18_27)
  L17_26 = L11_20
  L15_24 = L15_24(L16_25, L17_26)
  L16_25 = Or
  L17_26 = And
  L18_27 = gConditionUnharmed
  L19_28 = conditionStateChangeAllowed
  L17_26 = L17_26(L18_27, L19_28)
  L18_27 = gConditionTransitionToBlockStateAllowed
  L24_33 = L16_25(L17_26, L18_27)
  L14_23 = L14_23(L15_24, L16_25, L17_26, L18_27, L19_28, L20_29, L21_30, L22_31, L23_32, L24_33, L16_25(L17_26, L18_27))
  L15_24 = CreateState
  L16_25 = L14_23
  L17_26 = "__hash_0x4add6eff"  -- stateBlock
  L15_24 = L15_24(L16_25, L17_26)
  stateBlock = L15_24
  L15_24 = stateBlock
  L16_25 = L15_24
  L15_24 = L15_24.SetCallbacks
  L17_26 = "StateBlock_Enter"
  L18_27 = "StateBlock_Exit"
  L15_24(L16_25, L17_26, L18_27)
  L15_24 = baseCharacterBodyStateSelector
  L16_25 = L15_24
  L15_24 = L15_24.Register
  L17_26 = stateBlock
  L15_24(L16_25, L17_26)
  L15_24 = Bool
  L16_25 = "__hash_0x67dab3ae"  -- blockStopStateRunning
  L17_26 = false
  L15_24 = L15_24(L16_25, L17_26)
  blockStopStateRunning = L15_24
  L15_24 = Equal
  L16_25 = blockStopStateRunning
  L17_26 = true
  L15_24 = L15_24(L16_25, L17_26)
  L16_25 = And
  L17_26 = And
  L18_27 = And
  L19_28 = Or
  L20_29 = gDesiredActionBlockStop
  L21_30 = L15_24
  L19_28 = L19_28(L20_29, L21_30)
  L20_29 = gConditionUnharmed
  L18_27 = L18_27(L19_28, L20_29)
  L19_28 = L11_20
  L17_26 = L17_26(L18_27, L19_28)
  L18_27 = conditionStateChangeAllowed
  L16_25 = L16_25(L17_26, L18_27)
  L17_26 = CreateState
  L18_27 = L16_25
  L19_28 = "__hash_0x8785e5b1"  -- stateBlockStop
  L17_26 = L17_26(L18_27, L19_28)
  stateBlockStop = L17_26
  L17_26 = stateBlockStop
  L18_27 = L17_26
  L17_26 = L17_26.SetCallbacks
  L19_28 = "StateBlockStop_Enter"
  L20_29 = "StateBlockStop_Exit"
  L17_26(L18_27, L19_28, L20_29)
  L17_26 = baseCharacterBodyStateSelector
  L18_27 = L17_26
  L17_26 = L17_26.Register
  L19_28 = stateBlockStop
  L17_26(L18_27, L19_28)
  L17_26 = engine
  L17_26 = L17_26.ScriptableVariableObserver
  L18_27 = GetScriptComponent
  L19_28 = __this__
  L18_27 = L18_27(L19_28)
  L19_28 = gTouching
  L20_29 = L19_28
  L19_28 = L19_28.UpCastToVariableProxy
  L24_33 = L19_28(L20_29)
  L17_26 = L17_26(L18_27, L19_28, L20_29, L21_30, L22_31, L23_32, L24_33, L19_28(L20_29))
  touchingObserver = L17_26
  L17_26 = touchingObserver
  L18_27 = L17_26
  L17_26 = L17_26.SetCallback
  L19_28 = "TouchingObserverCallback"
  L17_26(L18_27, L19_28)
  L17_26 = Bool
  L18_27 = "__hash_0x467d2b6c"  -- hurtStateRunning
  L19_28 = false
  L17_26 = L17_26(L18_27, L19_28)
  hurtStateRunning = L17_26
  L17_26 = And
  L18_27 = gConditionHurt
  L19_28 = And
  L20_29 = Not
  L21_30 = conditionReceiveStealthKill
  L20_29 = L20_29(L21_30)
  L21_30 = Not
  L22_31 = conditionReceiveSyncAction
  L24_33 = L21_30(L22_31)
  L24_33 = L19_28(L20_29, L21_30, L22_31, L23_32, L24_33, L21_30(L22_31))
  L17_26 = L17_26(L18_27, L19_28, L20_29, L21_30, L22_31, L23_32, L24_33, L19_28(L20_29, L21_30, L22_31, L23_32, L24_33, L21_30(L22_31)))
  conditionHurt = L17_26
  L17_26 = CreateState
  L18_27 = conditionHurt
  L19_28 = "__hash_0x0d545f69"  -- stateHurt
  L17_26 = L17_26(L18_27, L19_28)
  stateHurt = L17_26
  L17_26 = stateHurt
  L18_27 = L17_26
  L17_26 = L17_26.SetCallbacks
  L19_28 = "StateHurt_Enter"
  L20_29 = "StateHurt_Exit"
  L17_26(L18_27, L19_28, L20_29)
  L17_26 = baseCharacterBodyStateSelector
  L18_27 = L17_26
  L17_26 = L17_26.Register
  L19_28 = stateHurt
  L17_26(L18_27, L19_28)
  L17_26 = Bool
  L18_27 = "__hash_0xd606298e"  -- stuckInTrapStateRunning
  L19_28 = false
  L17_26 = L17_26(L18_27, L19_28)
  stuckInTrapStateRunning = L17_26
  L17_26 = Equal
  L18_27 = stuckInTrapStateRunning
  L19_28 = true
  L17_26 = L17_26(L18_27, L19_28)
  conditionStuckInTrapStateRunning = L17_26
  L17_26 = And
  L18_27 = And
  L19_28 = gConditionStuckInTrap
  L20_29 = And
  L21_30 = Not
  L22_31 = gConditionHurt
  L21_30 = L21_30(L22_31)
  L22_31 = gConditionNotDead
  L24_33 = L20_29(L21_30, L22_31)
  L18_27 = L18_27(L19_28, L20_29, L21_30, L22_31, L23_32, L24_33, L20_29(L21_30, L22_31))
  L19_28 = Not
  L20_29 = conditionReceiveSyncActionStateRunning
  L24_33 = L19_28(L20_29)
  L17_26 = L17_26(L18_27, L19_28, L20_29, L21_30, L22_31, L23_32, L24_33, L19_28(L20_29))
  conditionStuckInTrap = L17_26
  L17_26 = CreateState
  L18_27 = conditionStuckInTrap
  L19_28 = "__hash_0x2eea8f78"  -- stateStuckInTrap
  L17_26 = L17_26(L18_27, L19_28)
  stateStuckInTrap = L17_26
  L17_26 = stateStuckInTrap
  L18_27 = L17_26
  L17_26 = L17_26.SetCallbacks
  L19_28 = "StateStuckInTrap_Enter"
  L20_29 = "StateStuckInTrap_Exit"
  L17_26(L18_27, L19_28, L20_29)
  L17_26 = baseCharacterBodyStateSelector
  L18_27 = L17_26
  L17_26 = L17_26.Register
  L19_28 = stateStuckInTrap
  L17_26(L18_27, L19_28)
  L17_26 = Equal
  L18_27 = gDesiredActionSubTypeVar
  L19_28 = "EscapeTrap"
  L17_26 = L17_26(L18_27, L19_28)
  gDesiredActionEscapeTrap = L17_26
  L17_26 = Bool
  L18_27 = "__hash_0xabf4ed88"  -- EscapeTrap
  L19_28 = false
  L17_26 = L17_26(L18_27, L19_28)
  escapeTrapStateRunning = L17_26
  L17_26 = Equal
  L18_27 = escapeTrapStateRunning
  L19_28 = true
  L17_26 = L17_26(L18_27, L19_28)
  conditionEscapeTrapStateRunning = L17_26
  L17_26 = And
  L18_27 = Or
  L19_28 = gDesiredActionEscapeTrap
  L20_29 = conditionEscapeTrapStateRunning
  L18_27 = L18_27(L19_28, L20_29)
  L19_28 = gConditionUnharmedNoTrap
  L17_26 = L17_26(L18_27, L19_28)
  conditionEscapeTrap = L17_26
  L17_26 = CreateState
  L18_27 = conditionEscapeTrap
  L19_28 = "__hash_0xaee589b8"  -- stateEscapeTrap
  L17_26 = L17_26(L18_27, L19_28)
  stateEscapeTrap = L17_26
  L17_26 = stateEscapeTrap
  L18_27 = L17_26
  L17_26 = L17_26.SetCallbacks
  L19_28 = "StateEscapeTrap_Enter"
  L20_29 = "StateEscapeTrap_Exit"
  L17_26(L18_27, L19_28, L20_29)
  L17_26 = baseCharacterBodyStateSelector
  L18_27 = L17_26
  L17_26 = L17_26.Register
  L19_28 = stateEscapeTrap
  L17_26(L18_27, L19_28)
  L17_26 = And
  L18_27 = Not
  L19_28 = gConditionLocalNavigationForInteract
  L18_27 = L18_27(L19_28)
  L19_28 = And
  L20_29 = Not
  L21_30 = gConditionChargeHitStunt
  L20_29 = L20_29(L21_30)
  L21_30 = And
  L22_31 = And
  L23_32 = gConditionStunt
  L24_33 = And
  L24_33 = L24_33(And(gConditionNotDead, gConditionNotHurt), And(Not(conditionReceiveSyncAction), Not(conditionReceiveStealthKill)))
  L22_31 = L22_31(L23_32, L24_33, L24_33(And(gConditionNotDead, gConditionNotHurt), And(Not(conditionReceiveSyncAction), Not(conditionReceiveStealthKill))))
  L23_32 = And
  L24_33 = gConditionNotHidden
  L24_33 = L23_32(L24_33, And(Not(conditionStuckInTrap), Not(conditionReceiveScareAttack)))
  L24_33 = L21_30(L22_31, L23_32, L24_33, L23_32(L24_33, And(Not(conditionStuckInTrap), Not(conditionReceiveScareAttack))))
  L24_33 = L19_28(L20_29, L21_30, L22_31, L23_32, L24_33, L21_30(L22_31, L23_32, L24_33, L23_32(L24_33, And(Not(conditionStuckInTrap), Not(conditionReceiveScareAttack)))))
  L17_26 = L17_26(L18_27, L19_28, L20_29, L21_30, L22_31, L23_32, L24_33, L19_28(L20_29, L21_30, L22_31, L23_32, L24_33, L21_30(L22_31, L23_32, L24_33, L23_32(L24_33, And(Not(conditionStuckInTrap), Not(conditionReceiveScareAttack))))))
  conditionStunt = L17_26
  L17_26 = CreateState
  L18_27 = conditionStunt
  L19_28 = "__hash_0xabe7faa3"  -- stateStunt
  L17_26 = L17_26(L18_27, L19_28)
  stateStunt = L17_26
  L17_26 = stateStunt
  L18_27 = L17_26
  L17_26 = L17_26.SetCallbacks
  L19_28 = "StateStunt_Enter"
  L20_29 = "StateStunt_Exit"
  L17_26(L18_27, L19_28, L20_29)
  L17_26 = baseCharacterBodyStateSelector
  L18_27 = L17_26
  L17_26 = L17_26.Register
  L19_28 = stateStunt
  L17_26(L18_27, L19_28)
  L17_26 = And
  L18_27 = And
  L19_28 = gConditionChargeHitStunt
  L20_29 = And
  L21_30 = And
  L22_31 = gConditionNotDead
  L23_32 = gConditionNotHurt
  L21_30 = L21_30(L22_31, L23_32)
  L22_31 = And
  L23_32 = Not
  L24_33 = conditionReceiveSyncAction
  L23_32 = L23_32(L24_33)
  L24_33 = Not
  L24_33 = L24_33(conditionReceiveStealthKill)
  L24_33 = L22_31(L23_32, L24_33, L24_33(conditionReceiveStealthKill))
  L24_33 = L20_29(L21_30, L22_31, L23_32, L24_33, L22_31(L23_32, L24_33, L24_33(conditionReceiveStealthKill)))
  L18_27 = L18_27(L19_28, L20_29, L21_30, L22_31, L23_32, L24_33, L20_29(L21_30, L22_31, L23_32, L24_33, L22_31(L23_32, L24_33, L24_33(conditionReceiveStealthKill))))
  L19_28 = And
  L20_29 = gConditionNotHidden
  L21_30 = And
  L22_31 = Not
  L23_32 = conditionStuckInTrap
  L22_31 = L22_31(L23_32)
  L23_32 = Not
  L24_33 = conditionReceiveScareAttack
  L24_33 = L23_32(L24_33)
  L24_33 = L21_30(L22_31, L23_32, L24_33, L23_32(L24_33))
  L24_33 = L19_28(L20_29, L21_30, L22_31, L23_32, L24_33, L21_30(L22_31, L23_32, L24_33, L23_32(L24_33)))
  L17_26 = L17_26(L18_27, L19_28, L20_29, L21_30, L22_31, L23_32, L24_33, L19_28(L20_29, L21_30, L22_31, L23_32, L24_33, L21_30(L22_31, L23_32, L24_33, L23_32(L24_33))))
  conditionChargeHitStunt = L17_26
  L17_26 = CreateState
  L18_27 = conditionChargeHitStunt
  L19_28 = "__hash_0xf0578fff"  -- stateChargeHitStunt
  L17_26 = L17_26(L18_27, L19_28)
  stateChargeHitStunt = L17_26
  L17_26 = stateChargeHitStunt
  L18_27 = L17_26
  L17_26 = L17_26.SetCallbacks
  L19_28 = "StateChargeHitStunt_Enter"
  L20_29 = "StateChargeHitStunt_Exit"
  L17_26(L18_27, L19_28, L20_29)
  L17_26 = baseCharacterBodyStateSelector
  L18_27 = L17_26
  L17_26 = L17_26.Register
  L19_28 = stateChargeHitStunt
  L17_26(L18_27, L19_28)
  L17_26 = And
  L18_27 = And
  L19_28 = gDesiredActionReceiveQuestionThreat
  L20_29 = gConditionUnharmed
  L18_27 = L18_27(L19_28, L20_29)
  L19_28 = conditionStateChangeAllowed
  L17_26 = L17_26(L18_27, L19_28)
  conditionQuestionThreat = L17_26
  L17_26 = CreateState
  L18_27 = conditionQuestionThreat
  L19_28 = "__hash_0x0a02edbd"  -- stateQuestionThreat
  L17_26 = L17_26(L18_27, L19_28)
  stateQuestionThreat = L17_26
  L17_26 = stateQuestionThreat
  L18_27 = L17_26
  L17_26 = L17_26.SetCallbacks
  L19_28 = "StateQuestionThreat_Enter"
  L20_29 = "StateQuestionThreat_Exit"
  L17_26(L18_27, L19_28, L20_29)
  L17_26 = baseCharacterBodyStateSelector
  L18_27 = L17_26
  L17_26 = L17_26.Register
  L19_28 = stateQuestionThreat
  L17_26(L18_27, L19_28)
  L17_26 = Bool
  L18_27 = "__hash_0x601366d5"  -- knockedDownOutStateRunning
  L19_28 = false
  L17_26 = L17_26(L18_27, L19_28)
  knockedDownOutStateRunning = L17_26
  L17_26 = Equal
  L18_27 = knockedDownOutStateRunning
  L19_28 = true
  L17_26 = L17_26(L18_27, L19_28)
  L18_27 = And
  L19_28 = gConditionUnharmed
  L20_29 = Or
  L21_30 = gDesiredActionKnockedDownOut
  L22_31 = L17_26
  L24_33 = L20_29(L21_30, L22_31)
  L18_27 = L18_27(L19_28, L20_29, L21_30, L22_31, L23_32, L24_33, L20_29(L21_30, L22_31))
  L19_28 = CreateState
  L20_29 = L18_27
  L21_30 = "__hash_0xd2541c5f"  -- stateKnockedDownOut
  L19_28 = L19_28(L20_29, L21_30)
  stateKnockedDownOut = L19_28
  L19_28 = stateKnockedDownOut
  L20_29 = L19_28
  L19_28 = L19_28.SetCallbacks
  L21_30 = "StateKnockedDownOut_Enter"
  L22_31 = "StateKnockedDownOut_Exit"
  L19_28(L20_29, L21_30, L22_31)
  L19_28 = baseCharacterBodyStateSelector
  L20_29 = L19_28
  L19_28 = L19_28.Register
  L21_30 = stateKnockedDownOut
  L19_28(L20_29, L21_30)
  L19_28 = And
  L20_29 = And
  L21_30 = Not
  L22_31 = conditionReceiveSyncActionStateRunning
  L21_30 = L21_30(L22_31)
  L22_31 = Not
  L23_32 = conditionReceiveStealthKillStateRunning
  L24_33 = L22_31(L23_32)
  L20_29 = L20_29(L21_30, L22_31, L23_32, L24_33, L22_31(L23_32))
  L21_30 = And
  L22_31 = Not
  L23_32 = conditionDoSyncActionStateRunning
  L22_31 = L22_31(L23_32)
  L23_32 = Not
  L24_33 = conditionDoStealthKillStateRunning
  L24_33 = L23_32(L24_33)
  L24_33 = L21_30(L22_31, L23_32, L24_33, L23_32(L24_33))
  L19_28 = L19_28(L20_29, L21_30, L22_31, L23_32, L24_33, L21_30(L22_31, L23_32, L24_33, L23_32(L24_33)))
  conditionNoSpecialKill = L19_28
  L19_28 = And
  L20_29 = And
  L21_30 = gConditionDying
  L22_31 = Not
  L23_32 = gConditionDead
  L24_33 = L22_31(L23_32)
  L20_29 = L20_29(L21_30, L22_31, L23_32, L24_33, L22_31(L23_32))
  L21_30 = conditionNoSpecialKill
  L19_28 = L19_28(L20_29, L21_30)
  conditionDying = L19_28
  L19_28 = CreateState
  L20_29 = conditionDying
  L21_30 = "__hash_0x1acf7226"  -- stateDying
  L19_28 = L19_28(L20_29, L21_30)
  stateDying = L19_28
  L19_28 = stateDying
  L20_29 = L19_28
  L19_28 = L19_28.SetCallbacks
  L21_30 = "StateDying_Enter"
  L22_31 = "StateDying_Exit"
  L19_28(L20_29, L21_30, L22_31)
  L19_28 = baseCharacterBodyStateSelector
  L20_29 = L19_28
  L19_28 = L19_28.Register
  L21_30 = stateDying
  L19_28(L20_29, L21_30)
  L19_28 = And
  L20_29 = Not
  L21_30 = gConditionWaitingToRespawn
  L20_29 = L20_29(L21_30)
  L21_30 = And
  L22_31 = gConditionDead
  L23_32 = And
  L24_33 = Not
  L24_33 = L24_33(conditionReceiveSyncActionStateRunning)
  L24_33 = L23_32(L24_33, Not(conditionReceiveStealthKillStateRunning))
  L24_33 = L21_30(L22_31, L23_32, L24_33, L23_32(L24_33, Not(conditionReceiveStealthKillStateRunning)))
  L19_28 = L19_28(L20_29, L21_30, L22_31, L23_32, L24_33, L21_30(L22_31, L23_32, L24_33, L23_32(L24_33, Not(conditionReceiveStealthKillStateRunning))))
  conditionDead = L19_28
  L19_28 = CreateState
  L20_29 = conditionDead
  L21_30 = "__hash_0x27fc1257"  -- stateDead
  L19_28 = L19_28(L20_29, L21_30)
  stateDead = L19_28
  L19_28 = stateDead
  L20_29 = L19_28
  L19_28 = L19_28.SetCallbacks
  L21_30 = "StateDead_Enter"
  L22_31 = "StateDead_Exit"
  L19_28(L20_29, L21_30, L22_31)
  L19_28 = baseCharacterBodyStateSelector
  L20_29 = L19_28
  L19_28 = L19_28.Register
  L21_30 = stateDead
  L19_28(L20_29, L21_30)
  L19_28 = And
  L20_29 = gConditionWaitingToRespawn
  L21_30 = And
  L22_31 = gConditionDead
  L23_32 = And
  L24_33 = Not
  L24_33 = L24_33(conditionReceiveSyncActionStateRunning)
  L24_33 = L23_32(L24_33, Not(conditionReceiveStealthKillStateRunning))
  L24_33 = L21_30(L22_31, L23_32, L24_33, L23_32(L24_33, Not(conditionReceiveStealthKillStateRunning)))
  L19_28 = L19_28(L20_29, L21_30, L22_31, L23_32, L24_33, L21_30(L22_31, L23_32, L24_33, L23_32(L24_33, Not(conditionReceiveStealthKillStateRunning))))
  conditionRespawn = L19_28
  L19_28 = CreateState
  L20_29 = conditionRespawn
  L21_30 = "__hash_0x18798043"  -- stateRespawn
  L19_28 = L19_28(L20_29, L21_30)
  stateRespawn = L19_28
  L19_28 = stateRespawn
  L20_29 = L19_28
  L19_28 = L19_28.SetCallbacks
  L21_30 = "StateRespawn_Enter"
  L22_31 = "StateRespawn_Exit"
  L19_28(L20_29, L21_30, L22_31)
  L19_28 = baseCharacterBodyStateSelector
  L20_29 = L19_28
  L19_28 = L19_28.Register
  L21_30 = stateRespawn
  L19_28(L20_29, L21_30)
  L19_28 = And
  L20_29 = And
  L21_30 = gConditionUnharmed
  L22_31 = Or
  L23_32 = gDesiredActionWalk
  L24_33 = And
  L24_33 = L24_33(gDesiredActionRun, Not(gconditionLockOrAim))
  L24_33 = L22_31(L23_32, L24_33, L24_33(gDesiredActionRun, Not(gconditionLockOrAim)))
  L20_29 = L20_29(L21_30, L22_31, L23_32, L24_33, L22_31(L23_32, L24_33, L24_33(gDesiredActionRun, Not(gconditionLockOrAim))))
  L21_30 = conditionStateChangeAllowed
  L19_28 = L19_28(L20_29, L21_30)
  conditionWalk = L19_28
  L19_28 = CreateState
  L20_29 = conditionWalk
  L21_30 = "__hash_0x47482126"  -- stateWalk
  L19_28 = L19_28(L20_29, L21_30)
  stateWalk = L19_28
  L19_28 = stateWalk
  L20_29 = L19_28
  L19_28 = L19_28.SetCallbacks
  L21_30 = "StateWalk_Enter"
  L22_31 = "StateWalk_Exit"
  L19_28(L20_29, L21_30, L22_31)
  L19_28 = baseCharacterBodyStateSelector
  L20_29 = L19_28
  L19_28 = L19_28.Register
  L21_30 = stateWalk
  L19_28(L20_29, L21_30)
  L19_28 = And
  L20_29 = And
  L21_30 = gConditionUnharmed
  L22_31 = gDesiredActionRun
  L20_29 = L20_29(L21_30, L22_31)
  L21_30 = conditionStateChangeAllowed
  L19_28 = L19_28(L20_29, L21_30)
  L20_29 = CreateState
  L21_30 = L19_28
  L22_31 = "__hash_0x33ef5d31"  -- stateRun
  L20_29 = L20_29(L21_30, L22_31)
  stateRun = L20_29
  L20_29 = stateRun
  L21_30 = L20_29
  L20_29 = L20_29.SetCallbacks
  L22_31 = "StateRun_Enter"
  L23_32 = "StateRun_Exit"
  L20_29(L21_30, L22_31, L23_32)
  L20_29 = baseCharacterBodyStateSelector
  L21_30 = L20_29
  L20_29 = L20_29.Register
  L22_31 = stateRun
  L20_29(L21_30, L22_31)
  L20_29 = And
  L21_30 = And
  L22_31 = gConditionUnharmed
  L23_32 = gDesiredActionGeneric
  L21_30 = L21_30(L22_31, L23_32)
  L22_31 = conditionStateChangeAllowed
  L20_29 = L20_29(L21_30, L22_31)
  L21_30 = CreateState
  L22_31 = L20_29
  L23_32 = "__hash_0x66b899ff"  -- stateGeneric
  L21_30 = L21_30(L22_31, L23_32)
  stateGeneric = L21_30
  L21_30 = stateGeneric
  L22_31 = L21_30
  L21_30 = L21_30.SetCallbacks
  L23_32 = "StateGeneric_Enter"
  L24_33 = "StateGeneric_Exit"
  L21_30(L22_31, L23_32, L24_33)
  L21_30 = baseCharacterBodyStateSelector
  L22_31 = L21_30
  L21_30 = L21_30.Register
  L23_32 = stateGeneric
  L21_30(L22_31, L23_32)
  L21_30 = And
  L22_31 = And
  L23_32 = And
  L24_33 = gConditionUnharmed
  L23_32 = L23_32(L24_33, gDesiredActionAim)
  L24_33 = Not
  L24_33 = L24_33(gConditionLockOn)
  L22_31 = L22_31(L23_32, L24_33, L24_33(gConditionLockOn))
  L23_32 = conditionStateChangeAllowed
  L21_30 = L21_30(L22_31, L23_32)
  L22_31 = CreateState
  L23_32 = L21_30
  L24_33 = "__hash_0x52f14cff"  -- stateAim
  L22_31 = L22_31(L23_32, L24_33)
  stateAim = L22_31
  L22_31 = stateAim
  L23_32 = L22_31
  L22_31 = L22_31.SetCallbacks
  L24_33 = "StateAim_Enter"
  L22_31(L23_32, L24_33, "StateAim_Exit")
  L22_31 = baseCharacterBodyStateSelector
  L23_32 = L22_31
  L22_31 = L22_31.Register
  L24_33 = stateAim
  L22_31(L23_32, L24_33)
  L22_31 = And
  L23_32 = And
  L24_33 = And
  L24_33 = L24_33(And(gConditionUnharmed, gDesiredActionIdle), Not(gConditionLockOn))
  L23_32 = L23_32(L24_33, conditionStateChangeAllowed)
  L24_33 = Not
  L24_33 = L24_33(L3_12)
  L22_31 = L22_31(L23_32, L24_33, L24_33(L3_12))
  conditionStateIdle = L22_31
  L22_31 = CreateState
  L23_32 = conditionStateIdle
  L24_33 = "__hash_0x16fdee66"  -- stateIdle
  L22_31 = L22_31(L23_32, L24_33)
  stateIdle = L22_31
  L22_31 = stateIdle
  L23_32 = L22_31
  L22_31 = L22_31.SetCallbacks
  L24_33 = "StateIdle_Enter"
  L22_31(L23_32, L24_33, "StateIdle_Exit")
  L22_31 = baseCharacterBodyStateSelector
  L23_32 = L22_31
  L22_31 = L22_31.Register
  L24_33 = stateIdle
  L22_31(L23_32, L24_33)
  L22_31 = And
  L23_32 = And
  L24_33 = And
  L24_33 = L24_33(gConditionNotDead, gDesiredActionIdle)
  L23_32 = L23_32(L24_33, gConditionKnockedDown)
  L24_33 = conditionStateChangeAllowed
  L22_31 = L22_31(L23_32, L24_33)
  L23_32 = CreateState
  L24_33 = L22_31
  L23_32 = L23_32(L24_33, "__hash_0xf408efef")  -- stateIdleDown
  stateIdleDown = L23_32
  L23_32 = stateIdleDown
  L24_33 = L23_32
  L23_32 = L23_32.SetCallbacks
  L23_32(L24_33, "StateIdleDown_Enter", "StateIdleDown_Exit")
  L23_32 = baseCharacterBodyStateSelector
  L24_33 = L23_32
  L23_32 = L23_32.Register
  L23_32(L24_33, stateIdleDown)
  L23_32 = And
  L24_33 = And
  L24_33 = L24_33(And(gConditionNotDead, Or(gDesiredActionWalk, gDesiredActionRun)), gConditionKnockedDown)
  L23_32 = L23_32(L24_33, conditionStateChangeAllowed)
  L24_33 = CreateState
  L24_33 = L24_33(L23_32, "__hash_0x7d2f081f")  -- stateCrawl
  stateCrawl = L24_33
  L24_33 = stateCrawl
  L24_33 = L24_33.SetCallbacks
  L24_33(L24_33, "StateCrawl_Enter", "StateCrawl_Exit")
  L24_33 = baseCharacterBodyStateSelector
  L24_33 = L24_33.Register
  L24_33(L24_33, stateCrawl)
  L24_33 = And
  L24_33 = L24_33(gDesiredActionEndGame, gConditionNotDead)
  stateEndGame = CreateState(L24_33, "__hash_0xe836d527")  -- stateEndGame
  stateEndGame:SetCallbacks("StateEndGame_Enter", "StateEndGame_Exit")
  baseCharacterBodyStateSelector:Register(stateEndGame)
  baseCharacterNewBodyHurtObserver = engine.ScriptableVariableObserver(GetScriptComponent(__this__), gNewBodyHurtVar:UpCastToVariableProxy())
  baseCharacterNewBodyHurtObserver:SetCallback("NewBodyHurtObserverCB")
end
L1_1 = {}
L1_1.Setup = L0_0
BaseCharacter = L1_1
function L1_1()
  if bodyCurrentThreadLegacy ~= nil then
    threads.DestroyThreadFunction(__this__, bodyCurrentThreadLegacy)
    bodyCurrentThreadLegacy = nil
  end
end
DestroyThread = L1_1
function L1_1(A0_34)
  if gQuestionThreatVar:GetValue() == true then
    gQuestionThreatVar:SetValue(false)
  end
  if questionThreatStateRunning:GetValue() == true then
    stateChangeAllowed:SetValue(true)
  end
end
TouchingObserverCallback = L1_1
function L1_1(A0_35)
  local L1_36, L2_37
  L1_36 = engine
  L1_36 = L1_36.VariableBoolProxy_Cast
  L2_37 = A0_35
  L1_36 = L1_36(L2_37)
  L2_37 = GetComponent
  L2_37 = L2_37(__this__, "Character Component")
  L2_37 = L2_37.GetLockOnTarget
  L2_37 = L2_37(L2_37)
  DisplayReticle(not L1_36:GetValue())
  if L1_36:GetValue() == true then
    engine.LockOnCameraMsg_SendMsg(true, L2_37, GetModeledObject(__this__), GetModeledObject(__this__))
  else
    engine.LockOnCameraMsg_SendMsg(false, L2_37, GetModeledObject(__this__), GetModeledObject(__this__))
  end
end
lockOnValueChange = L1_1
L1_1, L2_2 = nil, nil
L3_3 = UnnamedVector
L4_4 = engine
L4_4 = L4_4.Vector4
L5_5 = "__hash_0x00000000"
L5_5 = L4_4(L5_5, "__hash_0x00000000", "__hash_0x00000000", "__hash_0x00000000")
L3_3 = L3_3(L4_4, L5_5, L4_4(L5_5, "__hash_0x00000000", "__hash_0x00000000", "__hash_0x00000000"))
L4_4 = nil
L5_5 = Bool
L5_5 = L5_5("__hash_0x139ad1f4", false)
function OnCancelCharacterAction(A0_38, A1_39)
  if A1_39 == gCurrentActionSubTypeVar:GetValue() then
    StateInteract_Exit()
  end
end
function MonitorNavigation(A0_40, A1_41, A2_42)
  local L3_43, L4_44
  L3_43 = engine
  L3_43 = L3_43.Vector4
  L4_44 = A0_40.GetPosition
  L4_44 = L4_44(A0_40)
  L4_44 = L4_44.get
  L4_44 = L4_44(L4_44, "__hash_0x00000000")
  L3_43 = L3_43(L4_44, "__hash_0x00000000", A0_40:GetPosition():get("__hash_0x00000002"))
  L4_44 = engine
  L4_44 = L4_44.Vector4
  L4_44 = L4_44(A1_41:get("__hash_0x00000000"), "__hash_0x00000000", A1_41:get("__hash_0x00000002"))
  if A2_42 > L3_43:DistanceSquare3(L4_44) then
    return true
  else
    if baseCharacterCancelInteractionByInput and GetCharacterControllerComponent(__this__):GetLeftStickMagnitude() > 0.8 then
      StateNavigation_Exit()
    end
    return false
  end
end
function CancelNavigationAndInteractionByInput()
  local L0_45, L1_46
  L0_45 = true
  baseCharacterCancelInteractionByInput = L0_45
  L0_45 = nil
  baseCharacterCancelInteractionTimerByInput = L0_45
end
function ComputeNavigationTargetPosition()
  local L0_47, L1_48, L2_49, L3_50
  L0_47 = GetComponent
  L1_48 = __this__
  L2_49 = "Character Component"
  L0_47 = L0_47(L1_48, L2_49)
  L1_48 = L0_47
  L0_47 = L0_47.GetCurrentActionTarget
  L0_47 = L0_47(L1_48)
  L1_48 = GetModeledObject
  L2_49 = L0_47
  L1_48 = L1_48(L2_49)
  L2_49 = GetComponent
  L3_50 = __this__
  L2_49 = L2_49(L3_50, "Character Component")
  L3_50 = L2_49
  L2_49 = L2_49.GetCurrentActionInteractionJoint
  L2_49 = L2_49(L3_50)
  L3_50 = nil
  if L1_48 ~= nil then
    if L1_48:GetJointFromName(L2_49) == nil then
      print(__this__:GetName() .. " computeNavigationTargetPosition and pTargetTransfo is nil (Name:" .. L1_48:GetName() .. ") (joint:" .. L2_49 .. ")")
      L3_50 = L1_48:GetPosition()
    else
      L3_50 = L1_48:GetJointFromName(L2_49):GetWorldMatrix():GetPos()
    end
  end
  return L3_50
end
function CharMonitorNavigationThread()
  local L0_51, L1_52, L2_53, L3_54
  L0_51 = GetModeledObject
  L1_52 = __this__
  L0_51 = L0_51(L1_52)
  L2_53 = L0_51
  L1_52 = L0_51.GetPosition
  L1_52 = L1_52(L2_53)
  L2_53 = engine
  L2_53 = L2_53.Vector4
  L3_54 = L1_52
  L2_53 = L2_53(L3_54)
  L3_54 = ComputeNavigationTargetPosition
  L3_54 = L3_54()
  _UPVALUE0_:SetValue(false)
  while true do
    if L3_54 ~= nil then
      if "__hash_0x00000000" >= "__hash_0x0000012c" or "__hash_0x00000000" > "__hash_0x00000003" or MonitorNavigation(L0_51, L3_54, 0.1) then
        _UPVALUE0_:SetValue(true)
      end
    else
      StateInteract_Exit()
    end
    if L1_52:Distance3(L2_53) < 0.01 then
    else
      L2_53 = engine.Vector4(L1_52)
    end
    threads.WaitForTime(__this__, 0.02)
  end
  StopMonitorNavigation()
end
function StopMonitorNavigation()
  if _UPVALUE0_ ~= nil then
    threads.DestroyThreadFunction(__this__, _UPVALUE0_)
    _UPVALUE0_ = nil
  end
end
function StateNavigation_Enter()
  local L0_55, L1_56
  L0_55 = stateChangeAllowed
  L1_56 = L0_55
  L0_55 = L0_55.SetValue
  L0_55(L1_56, false)
  L0_55 = navigationStateRunning
  L1_56 = L0_55
  L0_55 = L0_55.SetValue
  L0_55(L1_56, true)
  L0_55 = GetComponent
  L1_56 = __this__
  L0_55 = L0_55(L1_56, "Script")
  L1_56 = stateLocalNavigationForInteract
  L1_56 = L1_56.GetValue
  L1_56 = L1_56(L1_56)
  if L1_56 == false then
    L1_56 = _UPVALUE0_
    if L1_56 == nil then
      L1_56 = engine
      L1_56 = L1_56.CharacterActionCancelMsgScriptListener_Create
      L1_56 = L1_56(L0_55)
      _UPVALUE0_ = L1_56
      L1_56 = _UPVALUE0_
      L1_56 = L1_56.BindScript
      L1_56(L1_56, "OnCancelCharacterAction")
    end
  end
  L1_56 = _UPVALUE1_
  if L1_56 == nil then
    L1_56 = threads
    L1_56 = L1_56.CreateThreadFunction
    L1_56 = L1_56(__this__, "CharMonitorNavigationThread")
    _UPVALUE1_ = L1_56
  end
  L1_56 = baseCharacterCancelInteractionTimerByInput
  if L1_56 == nil then
    L1_56 = CreateTimer
    L1_56 = L1_56(1, __this__, "CancelNavigationAndInteractionByInput")
    baseCharacterCancelInteractionTimerByInput = L1_56
    L1_56 = baseCharacterCancelInteractionTimerByInput
    L1_56 = L1_56.Start
    L1_56(L1_56)
  end
  L1_56 = StateWalk_Enter
  L1_56(false)
  L1_56 = ComputeNavigationTargetPosition
  L1_56 = L1_56()
  if L1_56 ~= nil then
    _UPVALUE2_:SetValue(L1_56)
    OrientToPosition(GetModeledObject(__this__), _UPVALUE2_, __this__.WalkHeadingRotationSpeed)
  else
    StateInteract_Exit()
  end
end
function StateNavigation_Exit()
  StateWalk_Exit()
  StopOrient(GetModeledObject(__this__))
  StopMonitorNavigation()
  if _UPVALUE0_ ~= nil then
    _UPVALUE0_:ReleaseScript("OnCancelCharacterAction")
    _UPVALUE0_ = nil
  end
  if baseCharacterCancelInteractionTimerByInput ~= nil then
    ReleaseTimer(baseCharacterCancelInteractionTimerByInput, __this__)
    baseCharacterCancelInteractionTimerByInput = nil
  end
  stateChangeAllowed:SetValue(true)
  navigationStateRunning:SetValue(false)
  baseCharacterCancelInteractionByInput = false
end
function DestroyInteractThread()
  if _UPVALUE0_ ~= nil then
    threads.DestroyThreadFunction(__this__, _UPVALUE0_)
    _UPVALUE0_ = nil
  end
  stateLocalNavigationForInteract:SetValue(false)
end
function StateInteract_Enter()
  GetComponent(__this__, "Character Component"):SetCurrentActionToDesiredAction()
  _UPVALUE0_ = threads.CreateThreadFunction(__this__, "StateInteract_Run")
end
function StateInteract_Run()
  if not IsInteractingObjectInHands() and not InteractionNoLocalNavigationException[gCurrentActionSubTypeVar:GetValue()] then
    stateLocalNavigationForInteract:SetValue(true)
    StateNavigation_Enter()
    if not _UPVALUE0_:GetValue() then
      threads.WaitForCondition(__this__, _UPVALUE1_)
    end
    stateLocalNavigationForInteract:SetValue(false)
    StateNavigation_Exit()
  else
    _UPVALUE0_:SetValue(true)
  end
  StateDoInteract_Enter()
  threads.WaitForTime(__this__, 0.1)
  DestroyInteractThread()
end
function StateInteract_Exit()
  DestroyInteractThread()
  if not _UPVALUE0_:GetValue() then
    StateNavigation_Exit()
    engine.CharacterActionCancelMsg_SendMsg(gCurrentActionTypeVar:GetValue(), gCurrentActionSubTypeVar:GetValue(), GetModeledObject(__this__))
  else
    StateDoInteract_Exit()
  end
end
function IsInteractingObjectInHands()
  if GetComponent(__this__, "Character Component"):GetCurrentActionTarget() ~= nil then
    if GetComponent(__this__, "Character Component"):GetRightHandModeledObject() ~= nil and GetComponent(__this__, "Character Component"):GetRightHandModeledObject():GetHashedName() == GetComponent(__this__, "Character Component"):GetCurrentActionTarget():GetHashedName() then
      return true
    end
    if GetComponent(__this__, "Character Component"):GetLeftHandModeledObject() ~= nil and GetComponent(__this__, "Character Component"):GetLeftHandModeledObject():GetHashedName() == GetComponent(__this__, "Character Component"):GetCurrentActionTarget():GetHashedName() then
      return true
    end
    if GetComponent(__this__, "Character Component"):GetBothHandsModeledObject() ~= nil and GetComponent(__this__, "Character Component"):GetBothHandsModeledObject():GetHashedName() == GetComponent(__this__, "Character Component"):GetCurrentActionTarget():GetHashedName() then
      return true
    end
  end
  return false
end
function CheckWeaponAnimationSpeed()
  if GetComponent(__this__, "Character Component"):GetRightHandModeledObject() ~= nil then
    attackAnimSpeed = GetComponent(__this__, "Character Component"):GetRightHandModeledObject():GetFloatLogicAttribute("AttackAnimSpeed")
  else
    attackAnimSpeed = 1.5
  end
end
CheckWeaponAnimationSpeed()
