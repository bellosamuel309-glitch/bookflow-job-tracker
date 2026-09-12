CREATE DATABASE IF NOT EXISTS book_services_db;
USE book_services_db;

-- Table to handle clients and staff roles
CREATE TABLE users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(50) NOT NULL UNIQUE,
    email VARCHAR(100) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    role ENUM('client', 'admin') DEFAULT 'client'
);

-- Table to track book service requests and workflow states
CREATE TABLE service_jobs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    client_id INT NOT NULL,
    book_title VARCHAR(150) NOT NULL,
    author_name VARCHAR(100) NOT NULL,
    service_type ENUM('Editing', 'Proofreading', 'Cover Design', 'Formatting') NOT NULL,
    details TEXT,
    status ENUM('Pending', 'In Progress', 'Under Review', 'Completed') DEFAULT 'Pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (client_id) REFERENCES users(id) ON DELETE CASCADE
);
