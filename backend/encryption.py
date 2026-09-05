"""
Account Number Encryption/Decryption
Encrypts account numbers in the database and provides a decrypt endpoint
that requires a valid decryption code.
"""

import os
import base64
import hashlib
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
import logging

logger = logging.getLogger(__name__)

class AccountEncryption:
    """Handle encryption and decryption of account numbers"""
    
    # Master encryption key - should be stored securely in production
    # For now, generate from a stable key or environment variable
    _cipher = None
    
    @classmethod
    def _get_cipher(cls):
        """Get or create the Fernet cipher for encryption"""
        if cls._cipher is None:
            # Try to get encryption key from environment, otherwise generate one
            key_str = os.getenv("ENCRYPTION_KEY")
            
            if not key_str:
                # Generate a new key if not provided (same key every time for this run)
                # In production, this should be stored securely in a secrets manager
                key = Fernet.generate_key()
                key_str = key.decode()
                logger.warning(
                    f"ENCRYPTION_KEY not set in environment. Using generated key (valid only for this session): {key_str}\n"
                    "For persistence, set ENCRYPTION_KEY in your .env file"
                )
            else:
                key = key_str.encode() if isinstance(key_str, str) else key_str
            
            try:
                cls._cipher = Fernet(key)
            except Exception as e:
                logger.error(f"Invalid ENCRYPTION_KEY format: {e}")
                raise ValueError("Invalid ENCRYPTION_KEY - must be a valid Fernet key")
        
        return cls._cipher
    
    @staticmethod
    def encrypt_account_number(account_number: str) -> str:
        """Encrypt an account number"""
        try:
            cipher = AccountEncryption._get_cipher()
            encrypted = cipher.encrypt(account_number.encode())
            return encrypted.decode()
        except Exception as e:
            logger.error(f"Failed to encrypt account number: {e}")
            raise
    
    @staticmethod
    def decrypt_account_number(encrypted_account_number: str) -> str:
        """Decrypt an encrypted account number using the master key"""
        try:
            cipher = AccountEncryption._get_cipher()
            decrypted = cipher.decrypt(encrypted_account_number.encode())
            return decrypted.decode()
        except Exception as e:
            logger.error(f"Failed to decrypt account number: {e}")
            raise ValueError("Failed to decrypt account number - invalid encrypted value or wrong key")
    
    @staticmethod
    def decrypt_with_code(encrypted_account_number: str, decryption_code: str) -> tuple[bool, str]:
        """
        Decrypt an account number using a decryption code.
        The code can be any string provided by the judge/administrator.
        
        Args:
            encrypted_account_number: The encrypted account number
            decryption_code: Code provided by user to unlock the account number
            
        Returns:
            Tuple of (success: bool, account_number_or_error: str)
        """
        try:
            # For MVP, we could implement various code verification strategies:
            # 1. Check against a hardcoded list of valid codes
            # 2. Check against a database of valid codes
            # 3. Check against hashed codes
            
            # For now, use environment variable approach or built-in codes
            valid_codes = os.getenv("DECRYPTION_CODES", "").split(",")
            valid_codes = [c.strip() for c in valid_codes if c.strip()]
            
            if decryption_code not in valid_codes:
                return False, "Invalid decryption code"
            
            decrypted = AccountEncryption.decrypt_account_number(encrypted_account_number)
            return True, decrypted
            
        except Exception as e:
            logger.error(f"Decryption code validation error: {e}")
            return False, str(e)
    
    @staticmethod
    def mask_account_number(account_number: str, show_last_n: int = 4) -> str:
        """
        Mask an account number, showing only the last N digits
        
        Args:
            account_number: The account number to mask
            show_last_n: Number of last digits to show
            
        Returns:
            Masked account number (e.g., "XXXXXXXX5667")
        """
        if len(account_number) <= show_last_n:
            return "X" * len(account_number)
        
        return "X" * (len(account_number) - show_last_n) + account_number[-show_last_n:]
    
    @staticmethod
    def _get_aes256_key() -> bytes:
        """
        Get or derive AES256 key for UTR encryption.
        Uses ENCRYPTION_KEY environment variable and derives a 256-bit key using SHA256.
        """
        key_str = os.getenv("ENCRYPTION_KEY", "default-utr-key")
        # Derive a 256-bit (32 byte) key using SHA256
        key = hashlib.sha256(key_str.encode()).digest()
        return key
    
    @staticmethod
    def encrypt_utr_aes256(utr_number: str) -> str:
        """
        Encrypt a UTR number using AES256-CBC encryption.
        
        Args:
            utr_number: The UTR number to encrypt
            
        Returns:
            Base64-encoded encrypted UTR (format: "AES256:<base64>")
        """
        try:
            key = AccountEncryption._get_aes256_key()
            # Generate a random 16-byte IV
            iv = os.urandom(16)
            
            # Create cipher and encryptor
            cipher = Cipher(
                algorithms.AES(key),
                modes.CBC(iv),
                backend=default_backend()
            )
            encryptor = cipher.encryptor()
            
            # Pad the message to AES block size (16 bytes)
            plaintext = utr_number.encode()
            padding_length = 16 - (len(plaintext) % 16)
            padded_plaintext = plaintext + bytes([padding_length] * padding_length)
            
            # Encrypt
            ciphertext = encryptor.update(padded_plaintext) + encryptor.finalize()
            
            # Return IV + ciphertext, base64 encoded with AES256 prefix
            encrypted_data = base64.b64encode(iv + ciphertext).decode()
            return f"AES256:{encrypted_data}"
            
        except Exception as e:
            logger.error(f"Failed to encrypt UTR with AES256: {e}")
            raise
    
    @staticmethod
    def decrypt_utr_aes256(encrypted_utr: str) -> str:
        """
        Decrypt a UTR number encrypted with AES256-CBC.
        
        Args:
            encrypted_utr: The encrypted UTR (format: "AES256:<base64>" or plain base64 for compatibility)
            
        Returns:
            The decrypted UTR number
        """
        try:
            # Handle both "AES256:<base64>" and plain base64 formats
            if encrypted_utr.startswith("AES256:"):
                encrypted_data = encrypted_utr[7:]  # Remove "AES256:" prefix
            else:
                encrypted_data = encrypted_utr
            
            key = AccountEncryption._get_aes256_key()
            
            # Decode from base64
            encrypted_bytes = base64.b64decode(encrypted_data)
            
            # Extract IV (first 16 bytes) and ciphertext (remaining bytes)
            iv = encrypted_bytes[:16]
            ciphertext = encrypted_bytes[16:]
            
            # Create cipher and decryptor
            cipher = Cipher(
                algorithms.AES(key),
                modes.CBC(iv),
                backend=default_backend()
            )
            decryptor = cipher.decryptor()
            
            # Decrypt
            padded_plaintext = decryptor.update(ciphertext) + decryptor.finalize()
            
            # Remove padding
            padding_length = padded_plaintext[-1]
            plaintext = padded_plaintext[:-padding_length]
            
            return plaintext.decode()
            
        except Exception as e:
            logger.error(f"Failed to decrypt UTR with AES256: {e}")
            raise ValueError("Failed to decrypt UTR - invalid encrypted value or wrong key")
