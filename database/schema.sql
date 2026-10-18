-- =====================================================================
-- ConnectSphere — MySQL Database Schema
-- =====================================================================

CREATE DATABASE IF NOT EXISTS connectsphere;
USE connectsphere;

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- ---------------------------------------------------------------------
-- User / role model
-- ---------------------------------------------------------------------

CREATE TABLE organisations (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    name            VARCHAR(255) NOT NULL,
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE users (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    organisation_id BIGINT UNSIGNED NULL,           -- set for Event Organisers / Attendees tied to a client org
    name            VARCHAR(255) NOT NULL,
    email           VARCHAR(255) NOT NULL UNIQUE,
    password_hash   VARCHAR(255) NOT NULL,
    is_active       TINYINT(1) NOT NULL DEFAULT 1,
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_users_organisation
        FOREIGN KEY (organisation_id) REFERENCES organisations(id)
        ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE roles (
    id              TINYINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    name            VARCHAR(50) NOT NULL UNIQUE      -- event_organiser, event_coordinator,
                                                       -- venue_staff, technical_support_staff, safety_officer, attendee
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE user_roles (
    user_id         BIGINT UNSIGNED NOT NULL,
    role_id         TINYINT UNSIGNED NOT NULL,
    PRIMARY KEY (user_id, role_id),
    CONSTRAINT fk_user_roles_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT fk_user_roles_role FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Supports JWT-based auth for the Vue SPA: tracks issued refresh tokens so
-- logout can revoke a session without waiting for natural token expiry.
CREATE TABLE refresh_tokens (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    user_id         BIGINT UNSIGNED NOT NULL,
    jti             CHAR(36) NOT NULL UNIQUE,
    revoked         TINYINT(1) NOT NULL DEFAULT 0,
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at      DATETIME NOT NULL,
    CONSTRAINT fk_refresh_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_refresh_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------------------------------------------------------------------
-- Event entity + status
-- (Event Request Creation, Draft Event Requests, Event Status Management)
-- ---------------------------------------------------------------------

CREATE TABLE events (
    id                      BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    name                    VARCHAR(255) NOT NULL,
    purpose                 VARCHAR(255) NOT NULL,
    description             TEXT NOT NULL,
    category                VARCHAR(100) NULL,

    organiser_id            BIGINT UNSIGNED NOT NULL,
    coordinator_id          BIGINT UNSIGNED NULL,        -- auto-assigned on submission (3.4)

    status ENUM(
        'draft','submitted','under_review','approved',
        'planning','safety_check','confirmed','completed','cancelled','rejected'
    ) NOT NULL DEFAULT 'draft',

    proposed_date           DATE NULL,
    proposed_time           TIME NULL,
    expected_attendance     INT UNSIGNED NULL,

    -- venueRequirements
    capacity_needed         INT UNSIGNED NULL,
    required_layout         VARCHAR(100) NULL,
    accessibility_needs     TEXT NULL,
    required_facilities     JSON NULL,                   -- list of facility names/codes

    registration_required   TINYINT(1) NOT NULL DEFAULT 0,
    intended_capacity       INT UNSIGNED NULL,
    registration_closed_at  DATETIME NULL,

    clarification_flag      TINYINT(1) NOT NULL DEFAULT 0,   -- sub-state of under_review
    clarification_comments  TEXT NULL,

    
    -- reviewDecision snapshot (latest decision; full history in event_reviews)
    review_outcome          ENUM('approved','rejected','returned') NULL,
    review_reason           TEXT NULL,
    review_timestamp        DATETIME NULL,
    review_coordinator_id   BIGINT UNSIGNED NULL,

    resubmitted_from_event_id BIGINT UNSIGNED NULL,        -- rejected -> new record on resubmission

    created_at              DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at              DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    submitted_at             DATETIME NULL,

    CONSTRAINT fk_events_organiser FOREIGN KEY (organiser_id) REFERENCES users(id),
    CONSTRAINT fk_events_coordinator FOREIGN KEY (coordinator_id) REFERENCES users(id),
    CONSTRAINT fk_events_review_coordinator FOREIGN KEY (review_coordinator_id) REFERENCES users(id),
    CONSTRAINT fk_events_resubmitted_from FOREIGN KEY (resubmitted_from_event_id) REFERENCES events(id),

    INDEX idx_events_organiser (organiser_id),
    INDEX idx_events_coordinator (coordinator_id),
    INDEX idx_events_status (status),
    INDEX idx_events_proposed_date (proposed_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- equipmentRequirements: [ { type, quantity, technicalNotes } ] from the event request itself
-- (distinct from equipment_reservations, which tracks actual reservations against the catalogue)
CREATE TABLE event_equipment_requirements (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    event_id        BIGINT UNSIGNED NOT NULL,
    equipment_type  VARCHAR(150) NOT NULL,
    quantity        INT UNSIGNED NOT NULL,
    technical_notes TEXT NULL,
    status          ENUM('requested','confirmed','unavailable') NOT NULL DEFAULT 'requested',
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_eer_event FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE,
    INDEX idx_eer_event (event_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------------------------------------------------------------------
-- Event Review and Approval — full history of review actions
-- (approve / reject / clarification requested / returned)
-- ---------------------------------------------------------------------

CREATE TABLE event_reviews (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    event_id        BIGINT UNSIGNED NOT NULL,
    coordinator_id  BIGINT UNSIGNED NOT NULL,
    action          ENUM('clarification_requested','approved','rejected','returned') NOT NULL,
    comments        TEXT NULL,
    editable_fields JSON NULL,  -- fields the Organiser may edit when responding to THIS specific request
    withdrawn_at    DATETIME NULL,        -- set when the Coordinator deletes/withdraws this request
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_er_event FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE,
    CONSTRAINT fk_er_coordinator FOREIGN KEY (coordinator_id) REFERENCES users(id),
    INDEX idx_er_event (event_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- One response per clarification request, enforced by the UNIQUE on review_id.
-- This is the "thread": each row pairs 1:1 with the event_reviews row
-- (action='clarification_requested') it answers.
CREATE TABLE event_clarification_responses (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    event_id        BIGINT UNSIGNED NOT NULL,
    review_id       BIGINT UNSIGNED NOT NULL UNIQUE,
    organiser_id    BIGINT UNSIGNED NOT NULL,
    comments        TEXT NOT NULL,
    updated_fields  JSON NULL,
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_ecr_event FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE,
    CONSTRAINT fk_ecr_review FOREIGN KEY (review_id) REFERENCES event_reviews(id) ON DELETE CASCADE,
    CONSTRAINT fk_ecr_organiser FOREIGN KEY (organiser_id) REFERENCES users(id),
    INDEX idx_ecr_event (event_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------------------------------------------------------------------
-- Event Status Management — audit trail of every status change
-- ---------------------------------------------------------------------

CREATE TABLE event_status_history (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    event_id        BIGINT UNSIGNED NOT NULL,
    old_status      VARCHAR(20) NULL,
    new_status      VARCHAR(20) NOT NULL,
    changed_by      BIGINT UNSIGNED NULL,
    reason          TEXT NULL,
    changed_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_esh_event FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE,
    CONSTRAINT fk_esh_user FOREIGN KEY (changed_by) REFERENCES users(id),
    INDEX idx_esh_event (event_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE event_safety_reviews (
    id                  BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    event_id            BIGINT UNSIGNED NOT NULL,
    safety_officer_id   BIGINT UNSIGNED NOT NULL,
    decision            ENUM('approved','rejected','changes_requested') NOT NULL,
    comments            TEXT NULL,
    assessed_factors    JSON NOT NULL,
    concern_factors     JSON NOT NULL,
    affected_arrangements JSON NOT NULL,
    created_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_esr_event FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE,
    CONSTRAINT fk_esr_safety_officer FOREIGN KEY (safety_officer_id) REFERENCES users(id),
    INDEX idx_esr_event (event_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

ALTER TABLE event_status_history
ADD COLUMN affected_fields JSON NULL;

-- ---------------------------------------------------------------------
-- Coordinator Assignment — auto-assignment + reassignment history
-- (keeps previous coordinator's read-only visibility)
-- ---------------------------------------------------------------------

CREATE TABLE event_coordinator_history (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    event_id        BIGINT UNSIGNED NOT NULL,
    coordinator_id  BIGINT UNSIGNED NOT NULL,
    assigned_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    unassigned_at   DATETIME NULL,
    assignment_type ENUM('auto','reassignment') NOT NULL DEFAULT 'auto',
    CONSTRAINT fk_ech_event FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE,
    CONSTRAINT fk_ech_coordinator FOREIGN KEY (coordinator_id) REFERENCES users(id),
    INDEX idx_ech_event (event_id),
    INDEX idx_ech_coordinator (coordinator_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------------------------------------------------------------------
-- Venue Catalogue
-- ---------------------------------------------------------------------

CREATE TABLE venues (
    id                      BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    name                    VARCHAR(255) NOT NULL,
    location                VARCHAR(255) NULL,
    capacity                INT UNSIGNED NOT NULL,
    description             TEXT NULL,
    accessibility_info      TEXT NULL,
    operating_hours         VARCHAR(255) NULL,
    is_active               TINYINT(1) NOT NULL DEFAULT 1,
    created_by              BIGINT UNSIGNED NULL,
    created_at              DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at              DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    setup_minutes           INT UNSIGNED NOT NULL DEFAULT 0,
    turnaround_minutes      INT UNSIGNED NOT NULL DEFAULT 0,
    CONSTRAINT fk_venues_creator FOREIGN KEY (created_by) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Search-filter options are stored per venue and maintained by Venue Staff.
-- The API derives the available layout options from active venue_layouts rows;
-- this is intentionally not a separate, hard-coded layout lookup list.
CREATE TABLE venue_layouts (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    venue_id        BIGINT UNSIGNED NOT NULL,
    layout_name     VARCHAR(100) NOT NULL,
    max_capacity    INT UNSIGNED NULL,
    CONSTRAINT fk_vl_venue FOREIGN KEY (venue_id) REFERENCES venues(id) ON DELETE CASCADE,
    UNIQUE KEY uq_venue_layout (venue_id, layout_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE venue_facilities (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    venue_id        BIGINT UNSIGNED NOT NULL,
    facility_name   VARCHAR(150) NOT NULL,
    CONSTRAINT fk_vf_venue FOREIGN KEY (venue_id) REFERENCES venues(id) ON DELETE CASCADE,
    UNIQUE KEY uq_venue_facility (venue_id, facility_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE venue_accessibility_features (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    venue_id        BIGINT UNSIGNED NOT NULL,
    feature_name    VARCHAR(150) NOT NULL,
    CONSTRAINT fk_vaf_venue FOREIGN KEY (venue_id) REFERENCES venues(id) ON DELETE CASCADE,
    UNIQUE KEY uq_venue_accessibility_feature (venue_id, feature_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------------------------------------------------------------------
-- Venue Availability Calendar — confirmed bookings (via venue_bookings)
-- plus other recorded unavailability (maintenance, etc.)
-- ---------------------------------------------------------------------

CREATE TABLE venue_unavailability (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    venue_id        BIGINT UNSIGNED NOT NULL,
    start_datetime  DATETIME NOT NULL,
    end_datetime    DATETIME NOT NULL,
    reason          VARCHAR(255) NULL,
    created_by      BIGINT UNSIGNED NULL,
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_vu_venue FOREIGN KEY (venue_id) REFERENCES venues(id) ON DELETE CASCADE,
    CONSTRAINT fk_vu_creator FOREIGN KEY (created_by) REFERENCES users(id),
    INDEX idx_vu_venue_dates (venue_id, start_datetime, end_datetime)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- ---------------------------------------------------------------------
-- Venue Booking Request / Approval / Rejection / Conflict Detection
-- Resubmission after rejection = new row (audit-friendly)
-- ---------------------------------------------------------------------

CREATE TABLE venue_bookings (
    id                  BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    event_id            BIGINT UNSIGNED NOT NULL,
    venue_id            BIGINT UNSIGNED NOT NULL,
    requested_by        BIGINT UNSIGNED NOT NULL,       -- Event Coordinator
    status              ENUM('pending','approved','rejected','withdrawn','cancelled','held','expired','released') NOT NULL DEFAULT 'pending',
    start_datetime        DATETIME NOT NULL,
    end_datetime          DATETIME NOT NULL,
    booking_label       VARCHAR(255) NULL,
    equipment           TEXT NULL,
    catering            TEXT NULL,
    other_requirements  TEXT NULL,
    hold_expires_at       DATETIME NULL,
    hold_warning_sent_at DATETIME NULL,
    hold_expired_notified_at DATETIME NULL,
    hold_released_at      DATETIME NULL,
    decision_reason       TEXT NULL,    
    alternative_suggestion TEXT NULL,
    decided_by            BIGINT UNSIGNED NULL,
    decided_at            DATETIME NULL,
    created_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_vb_event FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE,
    CONSTRAINT fk_vb_venue FOREIGN KEY (venue_id) REFERENCES venues(id),
    CONSTRAINT fk_vb_requested_by FOREIGN KEY (requested_by) REFERENCES users(id),
    CONSTRAINT fk_vb_decided_by FOREIGN KEY (decided_by) REFERENCES users(id),
    INDEX idx_vb_event (event_id),
    INDEX idx_vb_venue_dates (
        venue_id,
        start_datetime,
        end_datetime
    ),
    INDEX idx_vb_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;



-- ---------------------------------------------------------------------
-- Venue Availability Flags: raised when a venue's availability changes in
-- a way that affects an already-planned event (Week 7 change #2)
-- ---------------------------------------------------------------------

CREATE TABLE venue_availability_flags (
    id           BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    event_id     BIGINT UNSIGNED NOT NULL,
    venue_id     BIGINT UNSIGNED NOT NULL,
    reason       VARCHAR(255) NULL,
    resolved     TINYINT(1) NOT NULL DEFAULT 0,
    created_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at  DATETIME NULL,
    CONSTRAINT fk_avail_flag_event FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE,
    CONSTRAINT fk_avail_flag_venue FOREIGN KEY (venue_id) REFERENCES venues(id) ON DELETE CASCADE,
    INDEX idx_vaf_event (event_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- ---------------------------------------------------------------------
-- Equipment Availability Checking / Reservation (catalogue side)
-- ---------------------------------------------------------------------

CREATE TABLE equipment_items (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    name            VARCHAR(150) NOT NULL UNIQUE,
    category        VARCHAR(100) NULL,
    total_quantity  INT UNSIGNED NOT NULL,
    status          ENUM('active','maintenance','retired','damaged') NOT NULL DEFAULT 'active',
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE equipment_reservations (
    id                  BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    event_id            BIGINT UNSIGNED NOT NULL,
    equipment_requirement_id BIGINT UNSIGNED NULL,
    equipment_item_id   BIGINT UNSIGNED NOT NULL,
    quantity            INT UNSIGNED NOT NULL,
    status              ENUM('reserved','released') NOT NULL DEFAULT 'reserved',
    created_by          BIGINT UNSIGNED NULL,           -- Technical Support Staff
    start_datetime      DATETIME NOT NULL,
    end_datetime        DATETIME NOT NULL,
    created_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_eres_event FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE,
    CONSTRAINT fk_eres_requirement FOREIGN KEY (equipment_requirement_id) REFERENCES event_equipment_requirements(id) ON DELETE SET NULL,
    CONSTRAINT fk_eres_equipment FOREIGN KEY (equipment_item_id) REFERENCES equipment_items(id),
    CONSTRAINT fk_eres_created_by FOREIGN KEY (created_by) REFERENCES users(id),
    INDEX idx_eres_equipment_dates (equipment_item_id, start_datetime, end_datetime),
    INDEX idx_eres_event (event_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------------------------------------------------------------------
-- Attendee Registration
-- ---------------------------------------------------------------------

CREATE TABLE registrations (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    event_id        BIGINT UNSIGNED NOT NULL,
    attendee_id     BIGINT UNSIGNED NOT NULL,
    status          ENUM('registered','waitlisted','withdrawn') NOT NULL DEFAULT 'registered',
    registered_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_reg_event FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE,
    CONSTRAINT fk_reg_attendee FOREIGN KEY (attendee_id) REFERENCES users(id),
    UNIQUE KEY uq_registration (event_id, attendee_id),
    INDEX idx_reg_event_status (event_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------------------------------------------------------------------
-- Event Change Requests
-- ---------------------------------------------------------------------

CREATE TABLE change_requests (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  event_id BIGINT UNSIGNED NOT NULL,
  organiser_id BIGINT UNSIGNED NOT NULL,
  request_type ENUM('change','withdrawal') NOT NULL DEFAULT 'change',
  requested_changes JSON NOT NULL, -- field-level proposed changes
  is_significant TINYINT(1) NOT NULL DEFAULT 0,
  reason TEXT NOT NULL,

  -- pending | re_review | processed | rejected | cannot_accommodate
  status ENUM(
    'pending', 're_review', 'processed', 'rejected', 'cannot_accommodate'
  ) NOT NULL DEFAULT 'pending',

  coordinator_id BIGINT UNSIGNED NULL, -- who recorded the final outcome
  decision_reason TEXT NULL,
  decided_at DATETIME NULL,

  -- Who triggered re-review and when. The request remains unresolved while
  -- it is under re-review.
  re_review_by BIGINT UNSIGNED NULL,
  re_review_at DATETIME NULL,

  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

  CONSTRAINT fk_cr_event FOREIGN KEY (event_id)
    REFERENCES events(id) ON DELETE CASCADE,
  CONSTRAINT fk_cr_organiser FOREIGN KEY (organiser_id)
    REFERENCES users(id),
  CONSTRAINT fk_cr_coordinator FOREIGN KEY (coordinator_id)
    REFERENCES users(id),
  CONSTRAINT fk_cr_re_review_by FOREIGN KEY (re_review_by)
    REFERENCES users(id),

  INDEX idx_cr_event (event_id),
  INDEX idx_cr_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE event_change_history (
    id                  BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    event_id            BIGINT UNSIGNED NOT NULL,
    change_request_id   BIGINT UNSIGNED NOT NULL,
    field               VARCHAR(100) NOT NULL,
    old_value           JSON NULL,
    new_value           JSON NULL,
    changed_by          BIGINT UNSIGNED NOT NULL,
    changed_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_chg_hist_event FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE,
    CONSTRAINT fk_chg_hist_request FOREIGN KEY (change_request_id) REFERENCES change_requests(id) ON DELETE CASCADE,
    CONSTRAINT fk_chg_hist_user FOREIGN KEY (changed_by) REFERENCES users(id),
    INDEX idx_chg_hist_event (event_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE arrangement_flags (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  event_id BIGINT UNSIGNED NOT NULL,
  change_request_id BIGINT UNSIGNED NOT NULL,

  -- venue_booking | equipment
  kind ENUM('venue_booking', 'equipment') NOT NULL,
  target_id BIGINT UNSIGNED NOT NULL,

  reason VARCHAR(255) NOT NULL DEFAULT 'Needs reconsideration',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  cleared_at DATETIME NULL,

  CONSTRAINT fk_af_event FOREIGN KEY (event_id)
    REFERENCES events(id) ON DELETE CASCADE,
  CONSTRAINT fk_af_request FOREIGN KEY (change_request_id)
    REFERENCES change_requests(id) ON DELETE CASCADE,

  INDEX idx_af_request (change_request_id),
  INDEX idx_af_event (event_id),
  INDEX idx_af_target (kind, target_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------------------------------------------------------------------
-- Notification System
-- ---------------------------------------------------------------------

CREATE TABLE notifications (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    user_id         BIGINT UNSIGNED NOT NULL,
    event_id        BIGINT UNSIGNED NULL,
    type            VARCHAR(100) NOT NULL,           -- e.g. 'coordinator_assigned', 'booking_approved'
    message         VARCHAR(500) NOT NULL,
    is_read         TINYINT(1) NOT NULL DEFAULT 0,
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_notif_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT fk_notif_event FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE SET NULL,
    INDEX idx_notif_user_read (user_id, is_read),
    INDEX idx_notif_event (event_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------------------------------------------------------------------
-- Auditability (NFR f) — generic log for important actions across epics
-- ---------------------------------------------------------------------

CREATE TABLE audit_log (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    entity_type     VARCHAR(100) NOT NULL,           -- 'event', 'venue_booking', 'equipment_reservation', etc.
    entity_id       BIGINT UNSIGNED NOT NULL,
    action          VARCHAR(100) NOT NULL,
    performed_by    BIGINT UNSIGNED NULL,
    old_value       JSON NULL,
    new_value       JSON NULL,
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_audit_user FOREIGN KEY (performed_by) REFERENCES users(id),
    INDEX idx_audit_entity (entity_type, entity_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------------------------------------------------------------------
-- Seed lookup data
-- ---------------------------------------------------------------------

INSERT INTO roles (name) VALUES
    ('event_organiser'),
    ('event_coordinator'),
    ('venue_staff'),
    ('technical_support_staff'),
    ('safety_officer'),
    ('attendee');

SET FOREIGN_KEY_CHECKS = 1;

-- Event Information management: Add new columns for testing_status, installation_status, and needs_recheck to event_equipment_requirements table. Add new columns for setup_status, venue_notes, and needs_reconsideration to venue_bookings table. Create a new table event_field_edit_logs to log changes made to event fields.

ALTER TABLE event_equipment_requirements
    ADD COLUMN testing_status      ENUM('pending','in_progress','done') NOT NULL DEFAULT 'pending',
    ADD COLUMN installation_status ENUM('pending','in_progress','done') NOT NULL DEFAULT 'pending',
    ADD COLUMN needs_recheck       TINYINT(1) NOT NULL DEFAULT 0;

ALTER TABLE venue_bookings
    ADD COLUMN setup_status          ENUM('pending','in_progress','done') NOT NULL DEFAULT 'pending',
    ADD COLUMN venue_notes           TEXT NULL,
    ADD COLUMN needs_reconsideration TINYINT(1) NOT NULL DEFAULT 0;

CREATE TABLE event_field_edit_logs (
    id                BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    event_id          BIGINT UNSIGNED NOT NULL,
    changed_by        BIGINT UNSIGNED NULL,
    fields_changed    JSON NOT NULL,
    old_values        JSON NOT NULL,
    new_values        JSON NOT NULL,
    was_significant   TINYINT(1) NOT NULL DEFAULT 0,
    was_rejected      TINYINT(1) NOT NULL DEFAULT 0,
    rejection_reason  VARCHAR(500) NULL,
    created_at        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_efel_event FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE,
    CONSTRAINT fk_efel_user FOREIGN KEY (changed_by) REFERENCES users(id),
    INDEX idx_efel_event (event_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
-- ---------------------------------------------------------------------
-- Operational Safety Check: review list and per-factor assessment.
-- For an existing database, run just this block.
-- ---------------------------------------------------------------------

ALTER TABLE venues
    ADD COLUMN known_restrictions TEXT NULL;

ALTER TABLE event_safety_reviews
    ADD COLUMN factor_notes JSON NULL;

-- One in-progress assessment per event: outcome (satisfactory / concern) and
-- notes per factor. Cleared once the Safety Officer records a decision.
CREATE TABLE event_safety_assessments (
    id                  BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    event_id            BIGINT UNSIGNED NOT NULL,
    safety_officer_id   BIGINT UNSIGNED NOT NULL,
    factors             JSON NOT NULL,
    updated_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT uq_esa_event UNIQUE (event_id),
    CONSTRAINT fk_esa_event FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE,
    CONSTRAINT fk_esa_safety_officer FOREIGN KEY (safety_officer_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
