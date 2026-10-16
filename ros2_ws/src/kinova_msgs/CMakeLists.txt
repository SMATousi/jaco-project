cmake_minimum_required(VERSION 3.8)
project(kinova_msgs)

find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)

find_package(builtin_interfaces REQUIRED)
find_package(std_msgs REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(action_msgs REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/CartesianForce.msg"
  "msg/FingerPosition.msg"
  "msg/JointAngles.msg"
  "msg/JointTorque.msg"
  "msg/JointVelocity.msg"
  "msg/KinovaPose.msg"
  "msg/PoseVelocity.msg"
  "msg/PoseVelocityWithFingers.msg"
  "msg/PoseVelocityWithFingerVelocity.msg"
  "srv/AddPoseToCartesianTrajectory.srv"
  "srv/ClearTrajectories.srv"
  "srv/HomeArm.srv"
  "srv/RunCOMParametersEstimation.srv"
  "srv/SetEndEffectorOffset.srv"
  "srv/SetForceControlParams.srv"
  "srv/SetNullSpaceModeState.srv"
  "srv/SetTorqueControlMode.srv"
  "srv/SetTorqueControlParameters.srv"
  "srv/Start.srv"
  "srv/Stop.srv"
  "srv/ZeroTorques.srv"
  "action/ArmJointAngles.action"
  "action/ArmKinovaPose.action"
  "action/ArmPose.action"
  "action/SetFingersPosition.action"
  DEPENDENCIES
    builtin_interfaces
    std_msgs
    geometry_msgs
    action_msgs
)

ament_export_dependencies(rosidl_default_runtime)

ament_package()
