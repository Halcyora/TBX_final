"""
Account Number Encryption/Decryption
Encrypts account numbers in the database and provides a decrypt endpoint
that requires a valid decryption code.
"""

import os
from cryptography.fernet import Fernet
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
            Masked account number (e.g., "****13729069")
        """
        if len(account_number) <= show_last_n:
            return "*" * len(account_number)
        
        return "*" * (len(account_number) - show_last_n) + account_number[-show_last_n:]
