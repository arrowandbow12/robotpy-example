#
# Copyright (c) FIRST and other WPILib contributors.
# Open Source Software; you can modify and/or share it under the terms of
# the WPILib BSD license file in the root directory of this project.
#

# standard python imports
import math
import random

# project imports
from subsystems.drive.swervemodule import SwerveModule
import subsystems.drive.constants as constants
from utils.units import unit

# wpi imports
from wpilib import SmartDashboard, Field2d
import wpimath.geometry
from wpimath.geometry import Rotation2d, Pose2d, Twist2d
import wpimath.kinematics
from wpimath.kinematics import SwerveModuleState, ChassisSpeeds
import commands2
import ntcore
from pathplannerlib.auto import AutoBuilder
from pathplannerlib.config import HolonomicPathFollowerConfig, ReplanningConfig, PIDConstants
from wpilib import DriverStation

# vendor imports
from phoenix6.hardware.pigeon2 import Pigeon2

class Drivetrain(commands2.Subsystem):
    """
    Represents a swerve drive style drivetrain.
    """

    def __init__(self, isReal=True) -> None:

        self._isReal = isReal
        self._simPose = Pose2d()

        self.frontLeftLocation = wpimath.geometry.Translation2d((constants.kChassisWidth / 2.0).m_as("meter"), (constants.kChassisLength / 2.0).m_as("meter"))
        self.frontRightLocation = wpimath.geometry.Translation2d((constants.kChassisWidth / 2.0).m_as("meter"),(-constants.kChassisLength / 2.0).m_as("meter"))
        self.backLeftLocation = wpimath.geometry.Translation2d((-constants.kChassisWidth / 2.0).m_as("meter"), (constants.kChassisLength / 2.0).m_as("meter"))
        self.backRightLocation = wpimath.geometry.Translation2d((-constants.kChassisWidth / 2.0).m_as("meter"), (-constants.kChassisLength / 2.0).m_as("meter"))

        self.frontLeft = SwerveModule(**constants.frontLeft)
        self.frontRight = SwerveModule(**constants.frontRight)
        self.backLeft = SwerveModule(**constants.backLeft)
        self.backRight = SwerveModule(**constants.backRight)

        self.gyro = Pigeon2(constants.kGyroId)

        self.kinematics = wpimath.kinematics.SwerveDrive4Kinematics(
            self.frontLeftLocation,
            self.frontRightLocation,
            self.backLeftLocation,
            self.backRightLocation,
        )

        self.gyro.set_yaw(0)

        self.odometry = wpimath.kinematics.SwerveDrive4Odometry(
            self.kinematics,
            self.getPigeonRotation2d(),
            (
                self.frontLeft.getPosition(),
                self.frontRight.getPosition(),
                self.backLeft.getPosition(),
                self.backRight.getPosition(),
            )
        )

        self.field = Field2d()
        SmartDashboard.putData("odo_raw", self.field)

        nt = ntcore.NetworkTableInstance.getDefault()
        sms_topic = nt.getStructArrayTopic("/SwerveStates", SwerveModuleState)
        self.sms_pub = sms_topic.publish()

        smst_topic = nt.getStructArrayTopic("/SwerveStatesTarget", SwerveModuleState)
        self.smst_pub = smst_topic.publish()

        # Configure the AutoBuilder last
        AutoBuilder.configureHolonomic(
            self.getPose, # Robot pose supplier
            self.resetPose, # Method to reset odometry (will be called if your auto has a starting pose)
            self.getRobotRelativeSpeeds, # ChassisSpeeds supplier. MUST BE ROBOT RELATIVE
            self.driveRobotRelative, # Method that will drive the robot given ROBOT RELATIVE ChassisSpeeds
            HolonomicPathFollowerConfig( # HolonomicPathFollowerConfig, this should likely live in your Constants class
                PIDConstants(5.0, 1.0, 0.0), # Translation PID constants
                PIDConstants(7.0, 3.5, 0.0), # Rotation PID constants
                constants.kMaxSpeed.m_as("meter / second"), # Max module speed, in m/s
                constants.kChassisRadius.m_as("meter"), # Drive base radius in meters. Distance from robot center to furthest module.
                ReplanningConfig() # Default path replanning config. See the API for the options here
            ),
            self.shouldFlipPath, # Supplier to control path flipping based on alliance color
            self # Reference to this subsystem to set requirements
        )

    def shouldFlipPath(self):
        # Boolean supplier that controls when the path will be mirrored for the red alliance
        # This will flip the path being followed to the red side of the field.
        # THE ORIGIN WILL REMAIN ON THE BLUE SIDE
        return DriverStation.getAlliance() == DriverStation.Alliance.kRed

    def drive(
        self,
        xSpeed: float,
        ySpeed: float,
        rot: float,
        fieldRelative: bool,
        periodSeconds: float,
    ) -> None:
        """
        Method to drive the robot using joystick info.
        :param xSpeed: Speed of the robot in the x direction (forward).
        :param ySpeed: Speed of the robot in the y direction (sideways).
        :param rot: Angular rate of the robot.
        :param fieldRelative: Whether the provided x and y speeds are relative to the field.
        :param periodSeconds: Time
        """

        # swerveModuleStates = self.kinematics.toSwerveModuleStates(
        #     wpimath.kinematics.ChassisSpeeds.discretize(
        #         (
        #             wpimath.kinematics.ChassisSpeeds.fromFieldRelativeSpeeds(
        #                 xSpeed.m_as("meter / second"), ySpeed.m_as("meter / second"), rot.m_as("radian / second"), self.getPigeonRotation2d()
        #             )
        #             if fieldRelative
        #             else wpimath.kinematics.ChassisSpeeds(xSpeed, ySpeed, rot)
        #         ),
        #         periodSeconds,
        #     )
        # )
        # wpimath.kinematics.SwerveDrive4Kinematics.desaturateWheelSpeeds(
        #     swerveModuleStates, constants.kMaxSpeed.m_as("meter / second")
        # )

        swerveModuleStates = self.kinematics.toSwerveModuleStates(
            wpimath.kinematics.ChassisSpeeds.fromFieldRelativeSpeeds(
                    xSpeed.m_as("meter / second"), ySpeed.m_as("meter / second"), rot.m_as("radian / second"), self.getPigeonRotation2d()
                )
        )

        wpimath.kinematics.SwerveDrive4Kinematics.desaturateWheelSpeeds(
            swerveModuleStates, constants.kMaxSpeed.m_as("meter / second")
        )

        target_states = \
        [self.frontLeft.setDesiredState(swerveModuleStates[0]),
         self.frontRight.setDesiredState(swerveModuleStates[1]),
         self.backLeft.setDesiredState(swerveModuleStates[2]),
         self.backRight.setDesiredState(swerveModuleStates[3])]
        
        self.smst_pub.set(target_states)
    
    def driveRobotRelative(self, robotRelativeSpeeds: ChassisSpeeds):
        #TODO: Discretization
        swerveModuleStates = self.kinematics.toSwerveModuleStates(robotRelativeSpeeds)

        wpimath.kinematics.SwerveDrive4Kinematics.desaturateWheelSpeeds(
            swerveModuleStates, constants.kMaxSpeed.m_as("meter / second")
        )

        target_states = \
        [self.frontLeft.setDesiredState(swerveModuleStates[0]),
         self.frontRight.setDesiredState(swerveModuleStates[1]),
         self.backLeft.setDesiredState(swerveModuleStates[2]),
         self.backRight.setDesiredState(swerveModuleStates[3])]
        
        self.smst_pub.set(target_states)

    def updateOdometry(self) -> None:
        """Updates the field relative position of the robot."""

        self.frontLeft.update()
        self.frontRight.update()
        self.backLeft.update()
        self.backRight.update()

        self.odometry.update(
            self.getPigeonRotation2d(),
            (
                self.frontLeft.getPosition(),
                self.frontRight.getPosition(),
                self.backLeft.getPosition(),
                self.backRight.getPosition(),
            ),
        )

        SmartDashboard.putNumber("yaw", (self.getPigeonRotation2d().radians()))

        self.field.setRobotPose(self.odometry.getPose())
        self.sms_pub.set([self.frontLeft.getState(),self.frontRight.getState(),self.backLeft.getState(),self.backRight.getState()])

    def getPigeonRotation2d(self) -> Rotation2d:
        if self._isReal:
            return Rotation2d.fromDegrees(self.gyro.get_yaw().refresh().value)
        else:
            chSpds = self.kinematics.toChassisSpeeds([self.frontLeft.getState(),
                                                        self.frontRight.getState(),
                                                        self.backLeft.getState(),
                                                        self.backRight.getState(),])
            self._simPose = self._simPose.exp(
                Twist2d(chSpds.vx * 0.02, chSpds.vy * 0.02, chSpds.omega * 0.02)
            )
            noise = Rotation2d.fromDegrees(random.uniform(-1.25, 1.25))
            return self._simPose.rotation() + noise

    def getPose(self) -> Pose2d:
        return self.odometry.getPose()
    
    def resetPose(self, pose: Pose2d) -> None:
        self.odometry.resetPosition(self.getPigeonRotation2d(), (self.frontLeft.getPosition(), self.frontRight.getPosition(), self.backLeft.getPosition(), self.backRight.getPosition()), pose)

    def getRobotRelativeSpeeds(self) -> ChassisSpeeds:
        return self.kinematics.toChassisSpeeds((self.frontLeft.getState(), self.frontRight.getState(), self.backLeft.getState(), self.backRight.getState()))

    def periodic(self) -> None:
        self.updateOdometry()